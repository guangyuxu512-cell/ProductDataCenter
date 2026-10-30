"""供 RPA 只读查询商品；不暴露任何商品或分组写接口。"""

import hashlib
import re
from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Depends, Query, Response
from pydantic import BaseModel

from app.core.exceptions.errors import AppError
from app.core.security.access import require_rpa_access
from .api import get_service
from .errors import GroupNotFound, ProductNotFound
from .export import current_uu_bytes
from .queries import EXACT_PRODUCT_ID_PATTERN, ProductListOptions
from .schemas import GroupsRead
from .service import ProductService

router = APIRouter(prefix="/rpa/v1", tags=["rpa-products"], dependencies=[Depends(require_rpa_access)])
Service = Annotated[ProductService, Depends(get_service)]


class RpaProduct(BaseModel):
    product_id: str
    source_platform: str
    source_product_id: str | None = None
    title: str
    main_image_url: str | None = None


class RpaPage(BaseModel):
    items: list[RpaProduct]
    total: int | None
    limit: int
    offset: int


class UuVersionChanged(AppError):
    code = "RPA_UU_VERSION_CHANGED"
    message = "商品 UU 已变更，请重新确认本次任务"
    status_code = 409


@router.get("/product-groups", response_model=GroupsRead)
def groups(service: Service):
    return service.groups()


@router.get("/product-groups/{group_id}/products", response_model=RpaPage)
def group_products(group_id: UUID, service: Service, limit: int = Query(50, ge=1, le=200),
                   offset: int = Query(0, ge=0, le=2_147_483_647), include_total: bool = True):
    if not service.repository.group_exists(group_id):
        raise GroupNotFound()
    return service.repository.list(ProductListOptions(group_id=str(group_id), limit=limit, offset=offset,
                                                       include_total=include_total))


@router.get("/products/{product_id}/uu")
def product_uu(product_id: str, service: Service,
               expected_sha256: str | None = Query(None, min_length=64, max_length=64)):
    if len(product_id) > 128 or not EXACT_PRODUCT_ID_PATTERN.fullmatch(product_id):
        raise ProductNotFound()
    if expected_sha256 is not None and not re.fullmatch(r"[0-9a-f]{64}", expected_sha256):
        from .errors import ProductRequestError
        raise ProductRequestError("UU 校验值无效")
    rows = service.repository.export_rows([product_id])
    if not rows:
        raise ProductNotFound("商品不存在或没有可用的 UU")
    content, _ = current_uu_bytes(rows[0], service.settings.data_root, service.settings.export_max_bytes)
    digest = hashlib.sha256(content).hexdigest()
    if expected_sha256 is not None and expected_sha256 != digest:
        raise UuVersionChanged()
    return Response(content=content, media_type="application/json", headers={
        "X-UU-SHA256": digest, "Cache-Control": "no-store", "X-Content-Type-Options": "nosniff",
    })
