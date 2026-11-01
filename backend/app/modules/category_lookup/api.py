"""Read-only category candidates and attribute definitions for the editor."""
from threading import BoundedSemaphore, Lock
from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Response
from pydantic import BaseModel, Field, field_validator

from app.core.config import Settings, get_settings
from app.core.security.access import require_api_access
from app.modules.central.client import CentralApplicationClient, CentralConnectionError, eligible_douyin_shops
from .client import DouyinCategoryClient, LookupError

router = APIRouter(prefix="/api/v1/category-lookup", tags=["category-lookup"],
                   dependencies=[Depends(require_api_access)])
_lock = Lock()
_next = 0
_shop_limits: dict[UUID, BoundedSemaphore] = {}


class SearchBody(BaseModel):
    keyword: str = Field(min_length=1, max_length=120)

    @field_validator("keyword")
    @classmethod
    def clean_keyword(cls, value: str) -> str:
        value = value.strip()
        if not value:
            raise ValueError("请输入类目关键词")
        return value


class SchemaBody(BaseModel):
    shopId: UUID
    categoryId: str = Field(pattern=r"^[0-9]{1,20}$")
    title: str = Field(default="商品", max_length=120)


class Candidate(BaseModel):
    id: str
    name: str
    path: str


class Option(BaseModel):
    label: str
    value: str


class Attribute(BaseModel):
    id: str
    label: str
    required: bool
    options: list[Option]


class SearchResponse(BaseModel):
    shopId: UUID
    candidates: list[Candidate]


class SchemaResponse(BaseModel):
    categoryId: str
    attributes: list[Attribute]


def get_central(settings: Annotated[Settings, Depends(get_settings)]) -> CentralApplicationClient:
    return CentralApplicationClient(settings)


def get_lookup(settings: Annotated[Settings, Depends(get_settings)]) -> DouyinCategoryClient:
    return DouyinCategoryClient(settings)


def _shops(central: CentralApplicationClient):
    try:
        return sorted(eligible_douyin_shops(central.list_shops()), key=lambda shop: str(shop.shop_id))
    except CentralConnectionError:
        raise HTTPException(503, "中控店铺连接不可用") from None


def _session(central, shop_id):
    try:
        return central.read_session(shop_id, expected_platform="douyin")
    except CentralConnectionError:
        raise HTTPException(503, "店铺登录状态不可用") from None


def _limit(shop_id: UUID):
    with _lock:
        return _shop_limits.setdefault(shop_id, BoundedSemaphore(3))


def _fail(error: LookupError):
    messages = {"not_configured": "类目查询尚未启用", "invalid_configuration": "类目查询配置不可用",
                "session_unavailable": "店铺登录状态不可用", "signer_unavailable": "签名服务不可用",
                "platform_unavailable": "抖店接口暂不可用", "platform_rejected": "抖店未接受类目请求",
                "product_session_unavailable": "已授权店铺的商品页会话未通过抖店验证，请检查中控店铺登录状态",
                "invalid_schema": "抖店属性返回格式不支持", "invalid_response": "抖店类目返回格式不支持"}
    suffix = f"（代码 {error.platform_code}）" if error.platform_code is not None else ""
    raise HTTPException(503 if error.reason in {"not_configured", "invalid_configuration"} else 502,
                        messages.get(error.reason, "类目查询失败") + suffix) from None


@router.post("/search", response_model=SearchResponse)
def search(body: SearchBody, response: Response,
           central: Annotated[CentralApplicationClient, Depends(get_central)],
           lookup: Annotated[DouyinCategoryClient, Depends(get_lookup)]):
    response.headers["Cache-Control"] = "no-store"
    if not lookup.settings.douyin_category_lookup_enabled:
        _fail(LookupError("not_configured"))
    shops = _shops(central)
    if not shops:
        raise HTTPException(503, "没有可用的抖店登录状态")
    global _next
    with _lock:
        start = _next % len(shops)
        _next += 1
    # A shop can be valid for Compass but not yet have a usable product-page
    # session. Try each authorized shop at most once on the observed login
    # rejection; do not retry signing, network, or other platform failures.
    for shop in shops[start:] + shops[:start]:
        with _limit(shop.shop_id):
            session = _session(central, shop.shop_id)
            try:
                candidates = lookup.search(session, body.keyword)
            except LookupError as error:
                if error.reason == "platform_rejected" and error.platform_code == 10008:
                    continue
                _fail(error)
        return SearchResponse(shopId=shop.shop_id, candidates=candidates)
    _fail(LookupError("product_session_unavailable", 10008))


@router.post("/schema", response_model=SchemaResponse)
def schema(body: SchemaBody, response: Response,
           central: Annotated[CentralApplicationClient, Depends(get_central)],
           lookup: Annotated[DouyinCategoryClient, Depends(get_lookup)]):
    response.headers["Cache-Control"] = "no-store"
    if not lookup.settings.douyin_category_lookup_enabled:
        _fail(LookupError("not_configured"))
    if not any(shop.shop_id == body.shopId for shop in _shops(central)):
        raise HTTPException(403, "店铺未授权或登录状态不可用")
    with _limit(body.shopId):
        session = _session(central, body.shopId)
        try:
            attributes = lookup.schema(session, body.categoryId, body.title)
        except LookupError as error:
            _fail(error)
    return SchemaResponse(categoryId=body.categoryId, attributes=attributes)
