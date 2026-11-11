from typing import Annotated
from fastapi import APIRouter, Depends, HTTPException
from app.core.config import get_settings
from app.core.database.session import get_database_engine
from app.core.security.access import require_api_access, require_permission
from app.core.security.scoped_tokens import Principal
from app.modules.products.schemas import ProductIds
from .queue import PrecheckQueue

router = APIRouter(prefix="/api/v1/prechecks", tags=["product-prechecks"],
                   dependencies=[Depends(require_api_access)])


def _queue() -> PrecheckQueue:
    if not get_settings().auto_precheck_enabled:
        raise HTTPException(503, "自动预检尚未启用")
    return PrecheckQueue(get_database_engine())


@router.post("/query", dependencies=[Depends(require_permission("precheck.read"))])
def query_results(body: ProductIds, principal: Annotated[Principal, Depends(require_api_access)]):
    try:
        queue = _queue()
        return {"items": queue.results(body.productIds) if principal.groups is None else queue.results(body.productIds, allowed_groups=principal.groups)}
    except HTTPException:
        raise
    except Exception:
        raise HTTPException(503, "自动预检状态暂不可用") from None


@router.post("/run", dependencies=[Depends(require_permission("precheck.run"))])
def run_prechecks(body: ProductIds, principal: Annotated[Principal, Depends(require_api_access)]):
    """Put manual single/batch requests onto the automatic check queue."""
    try:
        queue = _queue()
        items = queue.enqueue(body.productIds) if principal.groups is None else queue.enqueue(body.productIds, allowed_groups=principal.groups)
    except HTTPException:
        raise
    except Exception:
        raise HTTPException(503, "预检请求暂不可用，商品数据未受影响") from None
    queued = {item["productId"] for item in items}
    return {"items": items, "missing": [item for item in body.productIds if item not in queued]}
