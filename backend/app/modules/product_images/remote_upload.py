"""Forward validated image uploads to a private NAS image service."""

import ipaddress
import json
import re
import tempfile
from pathlib import Path
from secrets import compare_digest
from urllib.parse import urlsplit

import httpx
from fastapi import HTTPException, Request
from fastapi.responses import StreamingResponse

from .urls import canonical_product_image_url

_PRIVATE_NETWORKS = tuple(ipaddress.ip_network(value) for value in (
    "10.0.0.0/8", "172.16.0.0/12", "192.168.0.0/16", "127.0.0.0/8", "100.64.0.0/10",
))
_TOKEN = re.compile(r"^[A-Za-z0-9_-]{16,256}$")
_NAME = re.compile(r"^[0-9a-f]{32}\.(?:jpg|png|gif|webp)$")


def _origin(value: str | None) -> str:
    """Allow HTTPS, or plain HTTP only to a literal private/Tailnet IPv4."""
    try:
        raw = (value or "").strip().rstrip("/")
        parts = urlsplit(raw)
        _ = parts.port
        if (not parts.hostname or parts.username is not None or parts.password is not None or "?" in raw or "#" in raw
                or parts.path or any(c.isspace() or ord(c) < 32 for c in raw)):
            raise ValueError()
        if parts.scheme == "http":
            address = ipaddress.ip_address(parts.hostname)
            if not isinstance(address, ipaddress.IPv4Address) or not any(address in net for net in _PRIVATE_NETWORKS):
                raise ValueError()
        elif parts.scheme != "https":
            raise ValueError()
        return raw
    except ValueError:
        raise HTTPException(503, "NAS 图片存储地址无效") from None


def _credential(path: Path | None) -> str:
    try:
        value = path.read_text(encoding="utf-8").strip() if path else ""
        if not _TOKEN.fullmatch(value):
            raise ValueError()
        return value
    except (OSError, UnicodeError, ValueError):
        raise HTTPException(503, "NAS 图片存储凭据不可用") from None


def _client() -> httpx.AsyncClient:
    # Do not allow proxy environment variables or redirects to expose the
    # storage-only credential to a third party.
    return httpx.AsyncClient(timeout=httpx.Timeout(120, connect=5), follow_redirects=False, trust_env=False)


async def read_source_image_from_nas(settings, relative_path: str):
    """Read an existing collection image without mounting NAS files on the server."""
    origin = _origin(settings.image_remote_upload_origin)
    token = _credential(settings.image_remote_upload_token_file)
    if any(value and compare_digest(token.encode(), value.encode())
           for value in (settings.configured_token(), settings.configured_rpa_token())):
        raise HTTPException(503, "NAS 图片存储凭据必须独立")
    client = _client()
    response = None
    try:
        request = client.build_request("POST", origin + "/internal/source-image",
                                       headers={"Authorization": "Bearer " + token}, json={"path": relative_path})
        response = await client.send(request, stream=True)
        if response.status_code == 404:
            raise HTTPException(404, "本地图片不存在")
        content_type = response.headers.get("content-type", "").split(";", 1)[0].lower()
        if response.status_code != 200 or content_type not in {"image/jpeg", "image/png", "image/gif", "image/webp"}:
            raise HTTPException(503, "NAS 图片读取失败")

        async def body():
            try:
                async for chunk in response.aiter_bytes():
                    yield chunk
            finally:
                await response.aclose()
                await client.aclose()

        return StreamingResponse(body(), media_type=content_type, headers={
            "Cache-Control": "private, max-age=60", "X-Content-Type-Options": "nosniff",
        })
    except HTTPException:
        if response is not None:
            await response.aclose()
        await client.aclose()
        raise
    except (OSError, httpx.HTTPError):
        if response is not None:
            await response.aclose()
        await client.aclose()
        raise HTTPException(503, "NAS 图片读取失败") from None


async def upload_to_nas(request: Request, settings, public_base: str, media_type: str, image_format):
    origin = _origin(settings.image_remote_upload_origin)
    token = _credential(settings.image_remote_upload_token_file)
    try:
        other_tokens = (settings.configured_token(), settings.configured_rpa_token())
        if any(value and compare_digest(token.encode(), value.encode()) for value in other_tokens):
            raise HTTPException(503, "NAS 图片存储凭据必须独立")
        # The temporary file is closed and removed after the request. The only
        # persistent copy is created by the NAS image service.
        with tempfile.TemporaryFile(mode="w+b") as output:
            size = 0
            header = b""
            async for chunk in request.stream():
                size += len(chunk)
                if size > settings.image_upload_max_bytes:
                    raise HTTPException(413, "图片大小不能超过 15 MB")
                header = (header + chunk)[:12]
                output.write(chunk)
            detected = image_format(header)
            if not detected or (media_type != "application/octet-stream" and media_type != detected[1]):
                raise HTTPException(415, "请选择 JPG、PNG、GIF 或 WebP 图片")
            output.seek(0)

            async def body():
                while chunk := output.read(64 * 1024):
                    yield chunk

            headers = {"Authorization": "Bearer " + token, "Content-Type": media_type, "Content-Length": str(size)}
            async with _client() as client:
                async with client.stream("POST", origin + "/api/v1/product-images", headers=headers, content=body()) as response:
                    if response.status_code != 201:
                        raise HTTPException(503, "NAS 图片保存失败")
                    raw = bytearray()
                    async for chunk in response.aiter_bytes():
                        if len(chunk) > 4096 - len(raw):
                            raise HTTPException(503, "NAS 图片响应无效")
                        raw.extend(chunk)
            result = json.loads(raw)
            url = result.get("url") if isinstance(result, dict) else None
            # NAS may still return a configured former public origin. Validate
            # its exact owned-image route, then return the current public domain.
            url = (canonical_product_image_url(url, public_base, settings.image_legacy_base_urls)
                   if isinstance(url, str) else None)
            prefix = public_base + "/rpa/v1/product-images/"
            name = url[len(prefix):] if isinstance(url, str) and url.startswith(prefix) else ""
            if not _NAME.fullmatch(name) or not name.endswith("." + detected[0]):
                raise HTTPException(503, "NAS 图片响应无效")
            return {"url": url}
    except HTTPException:
        raise
    except (OSError, UnicodeError, ValueError, httpx.HTTPError):
        raise HTTPException(503, "NAS 图片保存失败") from None
