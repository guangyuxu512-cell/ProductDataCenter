from fastapi import APIRouter, Depends, HTTPException
from app.core.config import get_settings
from app.core.database.session import get_database_engine
from app.core.security.access import require_api_access
from app.modules.products.schemas import ProductIds
from .queue import PrecheckQueue

router = APIRouter(prefix="/api/v1/prechecks", tags=["product-prechecks"],
                   dependencies=[Depends(require_api_access)])


@router.post("/query")
def query_results(body: ProductIds):
    if not get_settings().auto_precheck_enabled:
        raise HTTPException(503, "自动预检尚未启用")
    try:
        return {"items": PrecheckQueue(get_database_engine()).results(body.productIds)}
    except Exception:
        raise HTTPException(503, "自动预检状态暂不可用") from None
