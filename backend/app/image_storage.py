"""Image-only NAS application; it does not initialize a product database."""

from contextlib import asynccontextmanager

from fastapi import Depends, FastAPI, HTTPException
from fastapi.responses import FileResponse
from pydantic import BaseModel, Field

from app.core.config import get_settings
from app.core.health import router as health_router
from app.core.security.access import require_api_access
from app.modules.product_images.api import router as images_router
from app.modules.products.export import resolve_data_file


class SourceImageRequest(BaseModel):
    path: str = Field(min_length=1, max_length=4096)


@asynccontextmanager
async def lifespan(app: FastAPI):
    settings = get_settings()
    if settings.image_remote_upload_origin or settings.image_remote_upload_token_file:
        raise RuntimeError("NAS 图片服务不能继续转发上传")
    yield


def create_image_storage_application() -> FastAPI:
    app = FastAPI(title="商品图片存储", docs_url=None, redoc_url=None, openapi_url=None, lifespan=lifespan)
    app.include_router(health_router)
    app.include_router(images_router)

    @app.post("/internal/source-image", dependencies=[Depends(require_api_access)])
    def read_source_image(body: SourceImageRequest):
        path = resolve_data_file(get_settings().data_root, body.path)
        if path is None or path.suffix.lower() not in {".jpg", ".jpeg", ".png", ".webp", ".gif"}:
            raise HTTPException(404, "图片不存在")
        return FileResponse(path, headers={"X-Content-Type-Options": "nosniff"})

    return app


app = create_image_storage_application()
