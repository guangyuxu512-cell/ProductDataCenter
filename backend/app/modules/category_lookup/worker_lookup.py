"""Dispatch category lookups to an authorized Worker and receive direct results."""
from __future__ import annotations

import json
import re
import time
from uuid import UUID, uuid4

from app.modules.central.client import CentralApplicationClient, CentralConnectionError
from .cache import CacheUnavailable, CategoryCache


class LookupError(Exception):
    def __init__(self, reason: str, platform_code: int | str | None = None):
        super().__init__(reason)
        self.reason = reason
        self.platform_code = platform_code


def _safe_code(value):
    if type(value) is int and 0 <= value <= 10**20:
        return value
    if isinstance(value, str) and re.fullmatch(r"[A-Za-z0-9_.-]{1,64}", value):
        return value
    return None


def receive_lookup_result(settings, context, terminal, digest: str) -> None:
    """Authenticate via the existing delivery context before storing sanitized data."""
    from .client import normalize_category_options, normalize_predictions
    from app.modules.prechecks.worker_schema import read_worker_schema

    result = terminal.result
    operation = context.operation
    required = {"kind", "category_id", "device_id", "local_shop_id", "platform_shop_id", "http_status", "platform_code"}
    if operation != "schema":
        required.add("operation")
    required |= ({"items" if operation == "schema" else "data"} if terminal.status == "success"
                 else {"error_stage", "safe_error_code"})
    if (not isinstance(result, dict) or set(result) != required
            or result.get("kind") != "douyin.category_schema"
            or result.get("category_id") != context.category_id
            or result.get("device_id") != str(context.device_id)
            or result.get("local_shop_id") != context.local_shop_id
            or result.get("platform_shop_id") != context.platform_shop_id
            or (operation != "schema" and result.get("operation") != operation)):
        raise ValueError("worker identity mismatch")
    code = _safe_code(result.get("platform_code"))
    if result.get("platform_code") is not None and code is None:
        raise ValueError("invalid platform code")
    if terminal.status == "success":
        if result.get("http_status") != 200 or code not in (0, "0"):
            raise ValueError("invalid platform status")
        if operation == "schema":
            schema = read_worker_schema(result, expected_category_id=context.category_id)
            data = [field.model_dump(mode="json") for field in schema.attributes]
        elif operation == "tree":
            data = normalize_category_options(result["data"], context.category_id)
        elif operation == "predict":
            data = normalize_predictions(result["data"])
        elif operation == "search":
            data = result["data"]
            if (not isinstance(data, list) or len(data) > 200
                    or any(not isinstance(item, dict) or set(item) != {"id", "name", "path"}
                           or not re.fullmatch(r"[0-9]{1,32}", str(item.get("id") or ""))
                           or not isinstance(item.get("name"), str) or len(item["name"]) > 200
                           or not isinstance(item.get("path"), str) or len(item["path"]) > 500 for item in data)):
                raise ValueError("invalid search result")
        else:
            raise ValueError("invalid operation")
        saved = {"digest": digest, "status": "success", "data": data}
    else:
        stage, error = result.get("error_stage"), result.get("safe_error_code")
        if (stage not in {"session", "signer", "platform", "result"}
                or not isinstance(error, str) or not re.fullmatch(r"[A-Z][A-Z0-9_]{2,63}", error)
                or terminal.error_code != error):
            raise ValueError("invalid worker failure")
        saved = {"digest": digest, "status": "failed", "stage": stage, "error": error, "code": code}
    if len(json.dumps(saved, ensure_ascii=False).encode("utf-8")) > 4 * 1024 * 1024 + 16 * 1024:
        raise ValueError("result too large")
    CategoryCache(settings.category_cache_file).put_worker_result(str(context.task_id), saved)


def lookup(settings, *, operation: str, category_id: str, title: str,
           shop_id: UUID | None, image_url: str | None = None, timeout: float = 35.0):
    """Wait for the direct Worker response; the product service never receives a Session."""
    if not settings.worker_precheck_enabled:
        raise LookupError("not_configured")
    central = CentralApplicationClient(settings)
    claim = {"product_id": "lookup:" + uuid4().hex, "revision": 1, "attempts": 1}
    try:
        ticket = central.submit_worker_precheck(claim, category_id, title, delivery="product",
                                                operation=operation, image_url=image_url, shop_id=shop_id)
    except CentralConnectionError as error:
        raise LookupError("worker_unavailable" if error.reason == "upstream_unavailable" else error.reason) from None
    cache = CategoryCache(settings.category_cache_file)
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        try:
            value = cache.take_worker_result(str(ticket.task_id))
        except CacheUnavailable:
            raise LookupError("cache_unavailable") from None
        if value is not None:
            if value.get("status") == "success":
                return value["data"]
            if value.get("stage") == "session" and value.get("error") == "SHOP_SESSION_EXPIRED":
                raise LookupError("session_expired", value.get("code"))
            if value.get("stage") == "platform":
                raise LookupError("platform_rejected", value.get("code"))
            raise LookupError("worker_failed", value.get("code"))
        time.sleep(0.2)
    raise LookupError("worker_timeout")
