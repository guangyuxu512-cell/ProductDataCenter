from fastapi import FastAPI

from app.core.exceptions.handlers import install_exception_handlers
from app.core.health import router as health_router
from app.core.logging.request import RequestLoggingMiddleware
from app.modules.products.api import router as products_router


def create_application() -> FastAPI:
    app = FastAPI(title="商品云库", version="0.1.0", docs_url=None, redoc_url=None, openapi_url=None)
    app.add_middleware(RequestLoggingMiddleware)
    install_exception_handlers(app)
    app.include_router(health_router)
    app.include_router(products_router)
    # 现有库的 schema_migrations 由手机采集项目唯一管理，本服务不执行 DDL。
    return app


app = create_application()
