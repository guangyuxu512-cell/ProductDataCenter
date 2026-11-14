"""Canonical URLs for images owned by the product library."""

from __future__ import annotations

import json
import re
from urllib.parse import urlsplit


_IMAGE_PATH = re.compile(r"/rpa/v1/product-images/[0-9a-f]{32}\.(?:jpg|png|gif|webp)$")


def _bases(value: str) -> list[str]:
    return [item.strip().rstrip("/") for item in value.split(",") if item.strip()]


def _public_base(value: str | None) -> str | None:
    base = (value or "").strip().rstrip("/")
    try:
        parsed = urlsplit(base)
        _ = parsed.port
    except ValueError:
        return None
    if (parsed.scheme != "https" or not parsed.hostname or parsed.username or parsed.password
            or parsed.query or parsed.fragment
            or any(char.isspace() or ord(char) < 32 or ord(char) == 127 for char in base)):
        return None
    return base


def canonical_product_image_url(value: str | None, public_base: str | None,
                                legacy_bases: str = "") -> str | None:
    """Rewrite only an exact, configured product-image URL.

    Source-platform image URLs are intentionally untouched, even when their
    host happens to be private.  Compatibility is limited to the service's
    UUID filename route and to origins explicitly listed for this deployment.
    """
    if not value:
        return value
    public = _public_base(public_base)
    if not public:
        return value
    for base in _bases(legacy_bases):
        prefix = base + "/rpa/v1/product-images/"
        if value.startswith(prefix):
            suffix = value[len(base):]
            if _IMAGE_PATH.fullmatch(suffix):
                return public + suffix
    return value


def canonical_image_values(value, public_base: str | None, legacy_bases: str = ""):
    """Rewrite configured owned-image URLs in a JSON-like value without mutating it."""
    if not public_base or not legacy_bases:
        return value
    if isinstance(value, str):
        return canonical_product_image_url(value, public_base, legacy_bases)
    if isinstance(value, list):
        return [canonical_image_values(item, public_base, legacy_bases) for item in value]
    if isinstance(value, dict):
        return {key: canonical_image_values(item, public_base, legacy_bases) for key, item in value.items()}
    return value


def canonical_package_text(value: str, public_base: str | None,
                           legacy_bases: str = "") -> str:
    if not public_base or not legacy_bases:
        return value
    data = json.loads(value)
    result = canonical_image_values(data, public_base, legacy_bases)
    return json.dumps(result, ensure_ascii=False, separators=(",", ":")) if result != data else value
