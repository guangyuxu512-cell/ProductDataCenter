"""Consume the control center's versioned application Session contract.

This client never exposes a Session through a product API. Cookies and the
application token exist only in the backend process during the request.
"""

import json
import re
from pathlib import Path
from urllib.parse import urlsplit
from uuid import UUID

import httpx
from pydantic import BaseModel, ConfigDict, Field, SecretStr, TypeAdapter, ValidationError

from app.core.config import Settings


_PREFIX = "/internal/applications/v1"
_MAX_RESPONSE_BYTES = 1024 * 1024


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
    session_version: int | None = Field(default=None, gt=0, strict=True)


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


class CentralApplicationClient:
    def __init__(self, settings: Settings, *, transport: httpx.BaseTransport | None = None):
        self._settings = settings
        self._transport = transport

    def list_shops(self, *, purpose: str = "generic") -> list[CentralShop]:
        if purpose not in {"generic", "merchant"}:
            raise CentralConnectionError("invalid_configuration")
        if purpose == "merchant":
            payload, metadata_supported = self._get(
                f"{_PREFIX}/shops", require_no_store=True, merchant_metadata=True,
            )
            if not metadata_supported and isinstance(payload, list):
                # An old or intermediate central release cannot establish
                # that a returned version came from the metadata contract.
                payload = [{**row, "session_version": None} if isinstance(row, dict) else row
                           for row in payload]
        else:
            payload = self._get(f"{_PREFIX}/shops")
        try:
            return TypeAdapter(list[CentralShop]).validate_python(payload)
        except ValidationError:
            raise CentralConnectionError("invalid_response") from None

    def read_session(
        self, shop_id: UUID, expected_platform: str, *, purpose: str = "generic",
    ) -> CentralShopSession:
        if purpose not in {"generic", "merchant"}:
            raise CentralConnectionError("invalid_configuration")
        payload = self._get(
            f"{_PREFIX}/shops/{shop_id}/session", require_no_store=True,
            require_merchant=purpose == "merchant",
        )
        try:
            session = CentralShopSession.model_validate(payload)
        except ValidationError:
            raise CentralConnectionError("invalid_response") from None
        if session.shop_id != shop_id or session.platform != expected_platform:
            raise CentralConnectionError("invalid_response")
        return session

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

    def _get(
        self, path: str, *, require_no_store: bool = False,
        require_merchant: bool = False, merchant_metadata: bool = False,
    ):
        base_url, client_id, token = self._connection()
        headers = {"X-Application-ID": client_id, "Authorization": f"Bearer {token}",
                   "Cache-Control": "no-store"}
        if require_merchant or merchant_metadata:
            headers["X-Session-Purpose"] = "merchant"
        try:
            with httpx.Client(
                base_url=base_url, timeout=8.0, verify=True,
                follow_redirects=False, trust_env=False, transport=self._transport,
            ) as client:
                with client.stream(
                    "GET", path,
                    headers=headers,
                ) as response:
                    if response.status_code in (401, 403):
                        raise CentralConnectionError("authentication_failed")
                    if response.status_code == 409 and require_merchant:
                        error_body = bytearray()
                        for chunk in response.iter_bytes():
                            error_body.extend(chunk)
                            if len(error_body) > 4096:
                                raise CentralConnectionError("upstream_unavailable")
                        try:
                            error = json.loads(error_body)
                        except (UnicodeError, ValueError):
                            raise CentralConnectionError("upstream_unavailable") from None
                        if (isinstance(error, dict)
                                and error.get("code") == "APPLICATION_MERCHANT_IDENTITY_UNVERIFIED"):
                            raise CentralConnectionError("merchant_unverified")
                        raise CentralConnectionError("upstream_unavailable")
                    if response.status_code != 200:
                        raise CentralConnectionError("upstream_unavailable")
                    if require_no_store and "no-store" not in response.headers.get("cache-control", "").lower():
                        raise CentralConnectionError("invalid_response")
                    if require_merchant and response.headers.get("X-Merchant-Identity-Verified") != "1":
                        raise CentralConnectionError("merchant_verification_unavailable")
                    metadata_supported = response.headers.get("X-Session-Metadata-Version") == "1"
                    body = bytearray()
                    for chunk in response.iter_bytes():
                        body.extend(chunk)
                        if len(body) > _MAX_RESPONSE_BYTES:
                            raise CentralConnectionError("invalid_response")
            try:
                parsed = json.loads(body)
                return (parsed, metadata_supported) if merchant_metadata else parsed
            except (UnicodeError, ValueError):
                raise CentralConnectionError("invalid_response") from None
        except CentralConnectionError:
            raise
        except (httpx.HTTPError, OSError):
            raise CentralConnectionError("upstream_unavailable") from None


def eligible_douyin_shops(shops: list[CentralShop]) -> list[CentralShop]:
    """Use saved Session status as a candidate, not proof of platform login."""
    return [shop for shop in shops if shop.platform == "douyin" and shop.session_status in {"captured", "valid"}]
