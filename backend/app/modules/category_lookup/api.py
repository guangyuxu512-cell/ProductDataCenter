"""Read-only category candidates and attribute definitions for the editor."""
from threading import BoundedSemaphore, Lock
from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Response
from pydantic import BaseModel, Field, field_validator

from app.core.config import Settings, get_settings
from app.core.security.access import require_api_access
from app.modules.central.client import CentralApplicationClient, CentralConnectionError, eligible_douyin_shops
from .cache import CacheUnavailable, CategoryCache
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
    title: str = Field(default="商品", max_length=10000)
    refresh: bool = False


class AutoSchemaBody(BaseModel):
    categoryId: str = Field(pattern=r"^[0-9]{1,20}$")
    title: str = Field(default="商品", max_length=10000)
    refresh: bool = False

    @field_validator("categoryId")
    @classmethod
    def valid_category(cls, value: str) -> str:
        if not int(value):
            raise ValueError("缺少原类目 ID")
        return value


class Candidate(BaseModel):
    id: str
    name: str
    path: str


class TreeBody(BaseModel):
    parentId: str = Field(default="0", pattern=r"^[0-9]{1,20}$")
    shopId: UUID | None = None
    refresh: bool = False


class TreeItem(BaseModel):
    id: str
    name: str
    isLeaf: bool
    enabled: bool


class TreeResponse(BaseModel):
    shopId: UUID
    parentId: str
    items: list[TreeItem]
    fromCache: bool


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


class AutoSchemaResponse(SchemaResponse):
    shopId: UUID


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
                "invalid_schema": "抖店属性返回格式不支持", "invalid_tree": "抖店类目树返回格式不支持",
                "invalid_response": "抖店类目返回格式不支持"}
    suffix = f"（代码 {error.platform_code}）" if error.platform_code is not None else ""
    raise HTTPException(503 if error.reason in {"not_configured", "invalid_configuration"} else 502,
                        messages.get(error.reason, "类目查询失败") + suffix) from None


def _cache_call(operation, *args, **kwargs):
    try:
        return operation(*args, **kwargs)
    except CacheUnavailable:
        raise HTTPException(503, "类目缓存不可用，请检查商品库缓存配置") from None


def _available(central, lookup):
    if not lookup.settings.douyin_category_lookup_enabled:
        _fail(LookupError("not_configured"))
    shops = _shops(central)
    if not shops:
        raise HTTPException(503, "没有可用的抖店登录状态")
    return shops


def _auto_shop(central: CentralApplicationClient, lookup: DouyinCategoryClient, operation):
    shops = _available(central, lookup)
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
                result = operation(session)
            except LookupError as error:
                if error.reason == "platform_rejected" and error.platform_code == 10008:
                    continue
                _fail(error)
        return shop.shop_id, result
    _fail(LookupError("product_session_unavailable", 10008))


@router.post("/tree", response_model=TreeResponse)
def category_tree(body: TreeBody, response: Response,
                  central: Annotated[CentralApplicationClient, Depends(get_central)],
                  lookup: Annotated[DouyinCategoryClient, Depends(get_lookup)]):
    response.headers["Cache-Control"] = "no-store"
    shops = _available(central, lookup)
    if body.shopId and not any(shop.shop_id == body.shopId for shop in shops):
        raise HTTPException(403, "店铺未授权或登录状态不可用")
    if body.parentId != "0" and body.shopId is None:
        raise HTTPException(422, "读取下级类目需要沿用当前类目树")
    if body.refresh and body.parentId != "0":
        raise HTTPException(422, "请从根类目更新类目缓存")
    cache = CategoryCache(lookup.settings.category_cache_file)
    candidates = [shop for shop in shops if body.shopId is None or shop.shop_id == body.shopId]
    if not body.refresh:
        for shop in candidates:
            items = _cache_call(cache.get, "tree", str(shop.shop_id), body.parentId)
            if items is not None:
                return TreeResponse(shopId=shop.shop_id, parentId=body.parentId, items=items, fromCache=True)
    version = _cache_call(cache.tree_version)
    if body.shopId:
        with _limit(body.shopId):
            session = _session(central, body.shopId)
            try:
                items = lookup.category_options(session, body.parentId)
            except LookupError as error:
                _fail(error)
        shop_id = body.shopId
    else:
        shop_id, items = _auto_shop(central, lookup, lambda session: lookup.category_options(session, body.parentId))
    _cache_call(cache.put, "tree", str(shop_id), body.parentId, items,
                tree_version=version, refresh_tree=body.refresh)
    return TreeResponse(shopId=shop_id, parentId=body.parentId, items=items, fromCache=False)


@router.post("/search", response_model=SearchResponse)
def search(body: SearchBody, response: Response,
           central: Annotated[CentralApplicationClient, Depends(get_central)],
           lookup: Annotated[DouyinCategoryClient, Depends(get_lookup)]):
    response.headers["Cache-Control"] = "no-store"
    shop_id, candidates = _auto_shop(central, lookup, lambda session: lookup.search(session, body.keyword))
    return SearchResponse(shopId=shop_id, candidates=candidates)


@router.post("/schema/auto", response_model=AutoSchemaResponse)
def schema_auto(body: AutoSchemaBody, response: Response,
                central: Annotated[CentralApplicationClient, Depends(get_central)],
                lookup: Annotated[DouyinCategoryClient, Depends(get_lookup)]):
    response.headers["Cache-Control"] = "no-store"
    shops = _available(central, lookup)
    cache = CategoryCache(lookup.settings.category_cache_file)
    if not body.refresh:
        for shop in shops:
            attributes = _cache_call(cache.get, "schema", str(shop.shop_id), body.categoryId)
            if attributes is not None:
                return AutoSchemaResponse(shopId=shop.shop_id, categoryId=body.categoryId, attributes=attributes)
    version = _cache_call(cache.schema_version, body.categoryId)
    shop_id, attributes = _auto_shop(
        central, lookup, lambda session: lookup.schema(session, body.categoryId, body.title),
    )
    _cache_call(cache.put, "schema", str(shop_id), body.categoryId, attributes,
                refresh_schema=body.refresh, schema_version=version)
    return AutoSchemaResponse(shopId=shop_id, categoryId=body.categoryId, attributes=attributes)


@router.post("/schema", response_model=SchemaResponse)
def schema(body: SchemaBody, response: Response,
           central: Annotated[CentralApplicationClient, Depends(get_central)],
           lookup: Annotated[DouyinCategoryClient, Depends(get_lookup)]):
    response.headers["Cache-Control"] = "no-store"
    if not lookup.settings.douyin_category_lookup_enabled:
        _fail(LookupError("not_configured"))
    if not any(shop.shop_id == body.shopId for shop in _shops(central)):
        raise HTTPException(403, "店铺未授权或登录状态不可用")
    cache = CategoryCache(lookup.settings.category_cache_file)
    if not body.refresh:
        attributes = _cache_call(cache.get, "schema", str(body.shopId), body.categoryId)
        if attributes is not None:
            return SchemaResponse(categoryId=body.categoryId, attributes=attributes)
    version = _cache_call(cache.schema_version, body.categoryId)
    with _limit(body.shopId):
        session = _session(central, body.shopId)
        try:
            attributes = lookup.schema(session, body.categoryId, body.title)
        except LookupError as error:
            _fail(error)
    _cache_call(cache.put, "schema", str(body.shopId), body.categoryId, attributes,
                refresh_schema=body.refresh, schema_version=version)
    return SchemaResponse(categoryId=body.categoryId, attributes=attributes)
