from fastapi import FastAPI

from app.core.exceptions.handlers import install_exception_handlers
from app.core.health import router as health_router
from app.core.logging.request import RequestLoggingMiddleware
from app.modules.products.api import router as products_router
from app.modules.products.rpa_api import router as rpa_router
from app.modules.product_edit.api import router as editor_router
from app.modules.product_edit.assets import router as asset_router
from app.modules.source_categories.api import router as source_categories_router
from app.modules.source_categories.cache import (
    SourceCategoryNoStoreMiddleware, install_unexpected_error_no_store,
)


def create_application() -> FastAPI:
    app = FastAPI(title="商品云库", version="0.1.0", docs_url=None, redoc_url=None, openapi_url=None)
    app.add_middleware(RequestLoggingMiddleware)
    app.add_middleware(SourceCategoryNoStoreMiddleware)
    install_exception_handlers(app)
    install_unexpected_error_no_store(app)
    app.include_router(health_router)
    app.include_router(products_router)
    app.include_router(editor_router)
    app.include_router(asset_router)
    app.include_router(source_categories_router)
    app.include_router(rpa_router)
    # 现有库的 schema_migrations 由手机采集项目唯一管理，本服务不执行 DDL。
    return app


app = create_application()
