"""Validate a Worker's category-schema result using the existing product rules.

The transport returns only the platform's category-property items, not the
full platform response, request headers, or any Session material.  Normalizing
remains here so the product editor and precheck share one set of rules.
"""

from __future__ import annotations

import json
from typing import Any

from pydantic import ValidationError

from app.modules.category_lookup.api import Attribute, SchemaResponse
from app.modules.category_lookup.client import normalize_fields


MAX_WORKER_SCHEMA_BYTES = 4 * 1024 * 1024
_RESULT_FIELDS = frozenset({
    "kind", "category_id", "device_id", "local_shop_id", "platform_shop_id", "http_status", "platform_code", "items",
})


class WorkerSchemaResultError(ValueError):
    """An invalid or mismatched Worker result without platform content."""


def read_worker_schema(payload: Any, *, expected_category_id: str) -> SchemaResponse:
    """Convert a successful result into the same schema used by prechecks."""
    if not isinstance(payload, dict):
        raise WorkerSchemaResultError("invalid_result")
    if set(payload) != _RESULT_FIELDS:
        raise WorkerSchemaResultError("invalid_result")
    items = payload.get("items")
    if not isinstance(items, list):
        raise WorkerSchemaResultError("invalid_result")
    try:
        encoded = json.dumps(items, ensure_ascii=False, separators=(",", ":"),
                             allow_nan=False).encode("utf-8")
    except (TypeError, ValueError, UnicodeError):
        raise WorkerSchemaResultError("invalid_result") from None
    if len(encoded) > MAX_WORKER_SCHEMA_BYTES:
        raise WorkerSchemaResultError("result_too_large")
    if payload.get("kind") != "douyin.category_schema":
        raise WorkerSchemaResultError("invalid_result")
    if any(not isinstance(payload.get(key), str) or not payload[key].strip() or len(payload[key]) > 160
           for key in ("device_id", "local_shop_id", "platform_shop_id")):
        raise WorkerSchemaResultError("invalid_result")
    if payload.get("category_id") != expected_category_id:
        raise WorkerSchemaResultError("category_mismatch")
    if type(payload.get("http_status")) is not int or payload["http_status"] != 200:
        raise WorkerSchemaResultError("platform_request_failed")
    code = payload.get("platform_code")
    if not ((type(code) is int and code == 0) or (type(code) is str and code == "0")):
        raise WorkerSchemaResultError("platform_request_failed")
    try:
        attributes = [Attribute.model_validate(field) for field in normalize_fields(items)]
    except (TypeError, ValueError, ValidationError):
        raise WorkerSchemaResultError("invalid_result") from None
    return SchemaResponse(categoryId=expected_category_id, attributes=attributes)
