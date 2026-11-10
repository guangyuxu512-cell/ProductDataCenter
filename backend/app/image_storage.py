"""Image-only NAS application; it does not initialize a product database."""

from contextlib import asynccontextmanager

from fastapi import FastAPI

from app.core.config import get_settings
from app.core.health import router as health_router
from app.modules.product_images.api import router as images_router


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
    return app


app = create_image_storage_application()
