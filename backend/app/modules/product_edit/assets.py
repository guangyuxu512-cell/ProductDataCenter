"""仅保存用户主动上传的图片，不下载采集商品的远程图片。"""

import hashlib
import io
import os
import re
import tempfile
import warnings
from pathlib import Path

from fastapi import APIRouter, Depends, HTTPException, Request
from fastapi.responses import FileResponse
from PIL import Image, UnidentifiedImageError

from app.core.config import get_settings
from app.core.security.access import require_api_access, require_product_edits

router = APIRouter(prefix="/api/v1/product-assets", tags=["product-assets"],
                   dependencies=[Depends(require_api_access)])
MAX_BYTES = 10 * 1024 * 1024
MAX_PIXELS = 50_000_000
FORMATS = {"JPEG": ("jpg", "image/jpeg"), "PNG": ("png", "image/png"),
           "WEBP": ("webp", "image/webp"), "GIF": ("gif", "image/gif")}
ASSET_NAME = re.compile(r"^[0-9a-f]{64}\.(?:jpg|png|webp|gif)$", re.ASCII)


def _root() -> Path:
    root = get_settings().product_asset_root
    if root is None or not root.is_dir():
        raise HTTPException(503, "商品图片存储尚未配置")
    return root.resolve()


def _format(content: bytes) -> tuple[str, str]:
    try:
        with warnings.catch_warnings():
            warnings.simplefilter("error", Image.DecompressionBombWarning)
            with Image.open(io.BytesIO(content)) as image:
                result = FORMATS.get(image.format or "")
                if not result or image.width * image.height > MAX_PIXELS:
                    raise ValueError()
                image.verify()
                return result
    except (UnidentifiedImageError, OSError, SyntaxError, ValueError,
            Image.DecompressionBombWarning, Image.DecompressionBombError):
        raise HTTPException(400, "图片格式无效或尺寸过大") from None


@router.post("", dependencies=[Depends(require_product_edits)])
async def upload(request: Request):
    root = _root()
    length = request.headers.get("content-length")
    if length:
        try:
            if int(length) > MAX_BYTES:
                raise HTTPException(413, "图片超过 10 MB")
        except ValueError:
            raise HTTPException(400, "图片大小无效") from None
    data = bytearray()
    async for chunk in request.stream():
        data.extend(chunk)
        if len(data) > MAX_BYTES:
            raise HTTPException(413, "图片超过 10 MB")
    content = bytes(data)
    ext, _ = _format(content)
    digest = hashlib.sha256(content).hexdigest()
    name = f"{digest}.{ext}"
    target = root / name
    if target.exists():
        if target.is_symlink() or not target.is_file() or hashlib.sha256(target.read_bytes()).hexdigest() != digest:
            raise HTTPException(409, "图片存储校验失败")
    else:
        temp = None
        try:
            with tempfile.NamedTemporaryFile(dir=root, prefix=".upload-", delete=False) as handle:
                temp = Path(handle.name)
                handle.write(content)
                handle.flush()
                os.fsync(handle.fileno())
            try:
                os.link(temp, target)
            except FileExistsError:
                if target.is_symlink() or not target.is_file() or hashlib.sha256(target.read_bytes()).hexdigest() != digest:
                    raise HTTPException(409, "图片存储校验失败") from None
        except OSError:
            raise HTTPException(503, "商品图片保存失败") from None
        finally:
            if temp:
                temp.unlink(missing_ok=True)
    return {"url": f"/api/v1/product-assets/{name}", "sha256": digest}


@router.get("/{name}")
def read(name: str):
    if not ASSET_NAME.fullmatch(name):
        raise HTTPException(404, "图片不存在")
    root = _root()
    candidate = root / name
    path = candidate.resolve()
    if candidate.is_symlink() or not path.is_relative_to(root) or not path.is_file():
        raise HTTPException(404, "图片不存在")
    media_type = FORMATS[{"jpg": "JPEG", "png": "PNG", "webp": "WEBP", "gif": "GIF"}[path.suffix[1:]]][1]
    return FileResponse(path, media_type=media_type,
                        headers={"Cache-Control": "private, max-age=31536000, immutable", "X-Content-Type-Options": "nosniff"})
