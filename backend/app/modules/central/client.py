"""Consume the control center's versioned application Session contract.

This client never exposes a Session through a product API. Cookies and the
application token exist only in the backend process during the request.
"""

import json
import re
from pathlib import Path
from typing import Any, Literal
from urllib.parse import urlsplit
from uuid import UUID

import httpx
from pydantic import BaseModel, ConfigDict, Field, SecretStr, TypeAdapter, ValidationError

from app.core.config import Settings


_PREFIX = "/internal/applications/v1"
_MAX_RESPONSE_BYTES = 1024 * 1024
_MAX_WORKER_RESPONSE_BYTES = 4 * 1024 * 1024 + 16 * 1024
_WORKER_PRECHECKS = f"{_PREFIX}/worker-prechecks"


class CentralConnectionError(Exception):
    """A safe, non-sensitive error suitable for logs and connection status."""

    def __init__(self, reason: str):
        super().__init__(reason)
        self.reason = reason


class CentralShop(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    shop_id: UUID
    display_name: str
    platform: str
    session_status: str | None


class CentralCookie(BaseModel):
    model_config = ConfigDict(extra="ignore", frozen=True, populate_by_name=True)

    name: str = Field(min_length=1)
    value: SecretStr = Field(repr=False)
    domain: str | None = None
    path: str = "/"
    secure: bool = False
    http_only: bool = Field(default=False, alias="httpOnly")
    same_site: str | None = Field(default=None, alias="sameSite")
    expiration_date: float | None = Field(default=None, alias="expirationDate")


class CentralShopSession(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    shop_id: UUID
    platform: str
    session_version: int = Field(gt=0)
    cookies: tuple[CentralCookie, ...] = Field(min_length=1, repr=False)


class CentralWorkerPrecheckTicket(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    task_id: UUID
    status: Literal["pending", "running", "success", "failed", "lost"]


class CentralWorkerPrecheckState(CentralWorkerPrecheckTicket):
    result: dict[str, Any] | None = Field(default=None, repr=False)
    error_code: str | None = None
    error_message: str | None = Field(default=None, repr=False)


class CentralWorkerDeliveryContext(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    task_id: UUID
    client_id: str
    product_id: str = Field(min_length=1, max_length=128)
    revision: int = Field(gt=0)
    device_id: UUID
    category_id: str = Field(pattern=r"^[0-9]{1,32}$")
    local_shop_id: str = Field(min_length=1, max_length=160)
    platform_shop_id: str = Field(min_length=1, max_length=160)
    session_retry_supported: bool = False
    superseded: bool = False
    receipt_sha256: str | None = Field(default=None, pattern=r"^[0-9a-f]{64}$")


class CentralApplicationClient:
    def __init__(self, settings: Settings, *, transport: httpx.BaseTransport | None = None):
        self._settings = settings
        self._transport = transport

    def list_shops(self) -> list[CentralShop]:
        payload = self._get(f"{_PREFIX}/shops")
        try:
            return TypeAdapter(list[CentralShop]).validate_python(payload)
        except ValidationError:
            raise CentralConnectionError("invalid_response") from None

    def read_session(self, shop_id: UUID, expected_platform: str) -> CentralShopSession:
        payload = self._get(f"{_PREFIX}/shops/{shop_id}/session", require_no_store=True)
        try:
            session = CentralShopSession.model_validate(payload)
        except ValidationError:
            raise CentralConnectionError("invalid_response") from None
        if session.shop_id != shop_id or session.platform != expected_platform:
            raise CentralConnectionError("invalid_response")
        return session

    def submit_worker_precheck(self, claim: dict, category_id: str, title: str, *,
                               delivery: Literal["central", "product"] = "central") -> CentralWorkerPrecheckTicket:
        body = {"kind": "douyin.category_schema",
                "context": {"product_id": claim["product_id"], "revision": claim["revision"],
                            "attempt": claim["attempts"]},
                "input": {"category_id": category_id, "title": title}}
        if delivery == "product":
            body["delivery"] = delivery
        payload = self._request("POST", _WORKER_PRECHECKS, body=body, success_status=202)
        try:
            return CentralWorkerPrecheckTicket.model_validate(payload)
        except ValidationError:
            raise CentralConnectionError("invalid_response") from None

    def read_worker_precheck(self, task_id: UUID) -> CentralWorkerPrecheckState:
        payload = self._request("GET", f"{_WORKER_PRECHECKS}/{task_id}",
                                max_response_bytes=_MAX_WORKER_RESPONSE_BYTES, timeout=30.0)
        try:
            state = CentralWorkerPrecheckState.model_validate(payload)
        except ValidationError:
            raise CentralConnectionError("invalid_response") from None
        if state.task_id != task_id:
            raise CentralConnectionError("invalid_response")
        return state

    def worker_delivery_context(self, task_id: UUID, device_id: UUID, worker_token: str) -> CentralWorkerDeliveryContext:
        payload = self._request("GET", f"/api/v1/worker/tasks/{task_id}/precheck-delivery-context",
                                require_no_store=True, worker_credentials=(device_id, worker_token),
                                protocol_v2=True)
        try:
            context = CentralWorkerDeliveryContext.model_validate(payload)
        except ValidationError:
            raise CentralConnectionError("invalid_response") from None
        if (context.task_id != task_id or context.device_id != device_id
                or context.client_id != self._settings.central_application_id):
            raise CentralConnectionError("invalid_response")
        return context

    def _connection(self) -> tuple[str, str, str]:
        settings = self._settings
        if settings.central_application_enabled is None:
            raise CentralConnectionError("invalid_configuration")
        if not settings.central_application_enabled:
            raise CentralConnectionError("not_configured")
        base_url = settings.central_application_base_url or ""
        client_id = settings.central_application_id
        token_file = settings.central_application_token_file
        try:
            parsed = urlsplit(base_url)
            # Accessing .port also rejects malformed and out-of-range ports.
            _ = parsed.port
        except ValueError:
            raise CentralConnectionError("invalid_configuration") from None
        if (
            parsed.scheme != "https" or not parsed.hostname
            or parsed.username is not None or parsed.password is not None
            or parsed.path not in ("", "/") or parsed.query or parsed.fragment
            or not re.fullmatch(r"[a-z0-9][a-z0-9._-]{0,63}", client_id)
            or token_file is None
        ):
            raise CentralConnectionError("invalid_configuration")
        token = self._read_token(token_file)
        # Separate application credentials from the existing product/RPA keys.
        try:
            if token in (settings.configured_token(), settings.configured_rpa_token()):
                raise CentralConnectionError("invalid_configuration")
        except OSError:
            raise CentralConnectionError("invalid_configuration") from None
        return base_url.rstrip("/"), client_id, token

    @staticmethod
    def _read_token(path: Path) -> str:
        try:
            with path.open("r", encoding="ascii") as token_file:
                content = token_file.read(1025)
        except (OSError, UnicodeError):
            raise CentralConnectionError("invalid_configuration") from None
        if len(content) > 1024:
            raise CentralConnectionError("invalid_configuration")
        value = content.strip()
        if not re.fullmatch(r"[A-Za-z0-9_-]{32,256}", value):
            raise CentralConnectionError("invalid_configuration")
        return value

    def _get(self, path: str, *, require_no_store: bool = False):
        return self._request("GET", path, require_no_store=require_no_store)

    def _request(self, method: str, path: str, *, body: dict | None = None,
                 require_no_store: bool = False, success_status: int = 200,
                 max_response_bytes: int = _MAX_RESPONSE_BYTES, timeout: float = 8.0,
                 worker_credentials: tuple[UUID, str] | None = None, protocol_v2: bool = False):
        base_url, client_id, token = self._connection()
        try:
            with httpx.Client(
                base_url=base_url, timeout=timeout, verify=True,
                follow_redirects=False, trust_env=False, transport=self._transport,
            ) as client:
                options: dict[str, Any] = {"headers": {
                    "X-Application-ID": client_id, "Authorization": f"Bearer {token}",
                    "Cache-Control": "no-store"}}
                if worker_credentials is not None:
                    device_id, worker_token = worker_credentials
                    options["headers"] = {"X-Device-ID": str(device_id),
                                          "Authorization": f"Bearer {worker_token}",
                                          "Cache-Control": "no-store"}
                if protocol_v2:
                    options["headers"]["X-Precheck-Protocol"] = "2"
                if body is not None:
                    options["json"] = body
                with client.stream(method, path, **options) as response:
                    if worker_credentials is not None and response.status_code in (401, 403, 404):
                        raise CentralConnectionError("worker_denied")
                    if response.status_code in (401, 403):
                        raise CentralConnectionError("authentication_failed")
                    if response.status_code == 409 and path.startswith(_WORKER_PRECHECKS):
                        raise CentralConnectionError("idempotency_conflict")
                    if response.status_code != success_status:
                        raise CentralConnectionError("upstream_unavailable")
                    if require_no_store and "no-store" not in response.headers.get("cache-control", "").lower():
                        raise CentralConnectionError("invalid_response")
                    body = bytearray()
                    for chunk in response.iter_bytes():
                        body.extend(chunk)
                        if len(body) > max_response_bytes:
                            raise CentralConnectionError("invalid_response")
            try:
                return json.loads(body)
            except (UnicodeError, ValueError):
                raise CentralConnectionError("invalid_response") from None
        except CentralConnectionError:
            raise
        except (httpx.HTTPError, OSError):
            raise CentralConnectionError("upstream_unavailable") from None


def eligible_douyin_shops(shops: list[CentralShop]) -> list[CentralShop]:
    """Use saved Session status as a candidate, not proof of platform login."""
    return [shop for shop in shops if shop.platform == "douyin" and shop.session_status in {"captured", "valid"}]
