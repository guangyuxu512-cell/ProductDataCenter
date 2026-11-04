"""NAS-backed image uploads with stable, directly readable product URLs."""
import os
import re
import tempfile
from pathlib import Path
from urllib.parse import urlsplit
from uuid import uuid4

from fastapi import APIRouter, Depends, HTTPException, Request, status
from fastapi.responses import FileResponse

from app.core.config import get_settings
from app.core.security.access import require_api_access, require_product_writes

router = APIRouter(tags=["product-images"])
_NAME = re.compile(r"^[0-9a-f]{32}\.(?:jpg|png|gif|webp)$")


def _image_format(header: bytes) -> tuple[str, str] | None:
    if header.startswith(b"\xff\xd8\xff"):
        return "jpg", "image/jpeg"
    if header.startswith(b"\x89PNG\r\n\x1a\n"):
        return "png", "image/png"
    if header.startswith((b"GIF87a", b"GIF89a")):
        return "gif", "image/gif"
    if len(header) >= 12 and header.startswith(b"RIFF") and header[8:12] == b"WEBP":
        return "webp", "image/webp"
    return None


def _public_base(value: str | None) -> str:
    try:
        base = (value or "").strip().rstrip("/")
        parts = urlsplit(base)
        _ = parts.port
        if (parts.scheme not in {"http", "https"} or not parts.hostname or parts.username or parts.password
                or parts.query or parts.fragment or any(c.isspace() or ord(c) < 32 for c in base)):
            raise ValueError()
        return base
    except ValueError:
        raise HTTPException(503, "商品图片公网地址尚未配置") from None


def _storage_dir() -> Path:
    root = get_settings().image_storage_dir
    if root is None or not root.is_dir():
        raise HTTPException(503, "商品图片存储尚未配置")
    return root


@router.post("/api/v1/product-images", status_code=status.HTTP_201_CREATED,
             dependencies=[Depends(require_api_access), Depends(require_product_writes)])
async def upload_image(request: Request):
    settings = get_settings()
    base = _public_base(settings.image_public_base_url)
    root = _storage_dir()
    media_type = request.headers.get("content-type", "").split(";", 1)[0].strip().lower()
    if media_type not in {"image/jpeg", "image/png", "image/gif", "image/webp", "application/octet-stream"}:
        raise HTTPException(415, "请选择 JPG、PNG、GIF 或 WebP 图片")
    content_length = request.headers.get("content-length")
    if content_length:
        try:
            if int(content_length) > settings.image_upload_max_bytes:
                raise HTTPException(413, "图片大小不能超过 15 MB")
        except ValueError:
            raise HTTPException(400, "图片大小无效") from None
    temporary = None
    try:
        size = 0
        header = b""
        with tempfile.NamedTemporaryFile(dir=root, prefix=".upload-", delete=False) as output:
            temporary = Path(output.name)
            async for chunk in request.stream():
                size += len(chunk)
                if size > settings.image_upload_max_bytes:
                    raise HTTPException(413, "图片大小不能超过 15 MB")
                header = (header + chunk)[:12]
                output.write(chunk)
            image_format = _image_format(header)
            if not image_format or (media_type != "application/octet-stream" and media_type != image_format[1]):
                raise HTTPException(415, "请选择 JPG、PNG、GIF 或 WebP 图片")
            output.flush()
            os.fsync(output.fileno())
        name = f"{uuid4().hex}.{image_format[0]}"
        os.replace(temporary, root / name)
        temporary = None
        return {"url": f"{base}/rpa/v1/product-images/{name}"}
    except OSError:
        raise HTTPException(503, "商品图片保存失败，请检查 NAS 图片存储") from None
    finally:
        if temporary is not None:
            temporary.unlink(missing_ok=True)


@router.get("/rpa/v1/product-images/{name}")
def read_image(name: str):
    # Only images created by this service are exposed; no NAS path or original
    # filename can be supplied by a reader.
    if not _NAME.fullmatch(name):
        raise HTTPException(404, "图片不存在")
    root = _storage_dir().resolve()
    path = root / name
    if path.is_symlink() or not path.is_file():
        raise HTTPException(404, "图片不存在")
    media_types = {"jpg": "image/jpeg", "png": "image/png", "gif": "image/gif", "webp": "image/webp"}
    return FileResponse(path, media_type=media_types[path.suffix[1:]], headers={
        "Cache-Control": "public, max-age=31536000, immutable", "X-Content-Type-Options": "nosniff",
    })
