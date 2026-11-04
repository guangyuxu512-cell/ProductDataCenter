from contextlib import asynccontextmanager
from fastapi import FastAPI

from app.core.exceptions.handlers import install_exception_handlers
from app.core.health import router as health_router
from app.core.logging.request import RequestLoggingMiddleware
from app.modules.central.api import router as central_router
from app.modules.category_lookup.api import router as category_lookup_router
from app.modules.products.api import router as products_router
from app.modules.products.rpa_api import router as rpa_router
from app.modules.product_images.api import router as product_images_router
from app.modules.prechecks.api import router as precheck_router


@asynccontextmanager
async def lifespan(app: FastAPI):
    from app.core.config import get_settings
    settings = get_settings()
    runner = None
    if settings.auto_precheck_enabled:
        from app.core.database.session import get_database_engine
        from app.modules.prechecks.runner import PrecheckRunner
        runner = PrecheckRunner(get_database_engine(), settings)
        runner.start()
    try:
        yield
    finally:
        if runner:
            runner.stop()


def create_application() -> FastAPI:
    app = FastAPI(title="商品云库", version="0.1.0", docs_url=None, redoc_url=None, openapi_url=None, lifespan=lifespan)
    app.add_middleware(RequestLoggingMiddleware)
    install_exception_handlers(app)
    app.include_router(health_router)
    app.include_router(central_router)
    app.include_router(category_lookup_router)
    app.include_router(products_router)
    app.include_router(rpa_router)
    app.include_router(product_images_router)
    app.include_router(precheck_router)
    # 现有库的 schema_migrations 由手机采集项目唯一管理，本服务不执行 DDL。
    return app


app = create_application()
