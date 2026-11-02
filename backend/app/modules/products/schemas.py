from datetime import datetime
from decimal import Decimal
from typing import Literal
from uuid import UUID

from pydantic import BaseModel, Field, field_validator


class ProductRead(BaseModel):
    product_id: str
    source_platform: str
    source_product_id: str | None = None
    group_id: UUID | None = None
    group_name: str | None = None
    title: str
    title_status: str = ""
    shop_name: str = ""
    category_level_4: str = ""
    category_path: str = ""
    current_price_min: Decimal | None = None
    current_price_max: Decimal | None = None
    sku_count: int = 0
    main_image_count: int = 0
    detail_image_count: int = 0
    sku_image_count: int = 0
    main_image_url: str | None = None
    asset_rel_path: str = ""
    workbook_rel_path: str = ""
    raw_rel_path: str = ""
    captured_at: datetime | None = None
    updated_at: datetime | None = None


class ProductPage(BaseModel):
    items: list[ProductRead]
    total: int | None
    totalIncluded: bool
    limit: int
    offset: int


class SkuRead(BaseModel):
    sku_id: str
    sku_name: str
    current_price: Decimal | None = None
    image_rel_path: str = ""
    sort_order: int


class ImageRead(BaseModel):
    image_type: Literal["main", "detail", "sku"]
    sort_order: int
    rel_path: str
    source_url: str


class ProductDetail(BaseModel):
    product: ProductRead
    skus: list[SkuRead]
    images: list[ImageRead]
    sourceCategoryId: str | None = None


class GroupRead(BaseModel):
    groupId: UUID
    name: str
    productCount: int
    createdAt: datetime | None = None
    updatedAt: datetime | None = None


class GroupsRead(BaseModel):
    groups: list[GroupRead]


class GroupResponse(BaseModel):
    group: GroupRead


class GroupDeleted(BaseModel):
    groupId: UUID
    name: str
    productCount: int


class DeleteGroupResponse(BaseModel):
    deleted: GroupDeleted


class GroupName(BaseModel):
    name: str = Field(max_length=80)

    @field_validator("name")
    @classmethod
    def normalized_name(cls, value: str) -> str:
        value = " ".join(value.split())
        if not value:
            raise ValueError("请输入分组名称")
        return value


class ProductIds(BaseModel):
    productIds: list[str] = Field(min_length=1, max_length=200)

    @field_validator("productIds")
    @classmethod
    def valid_ids(cls, values: list[str]) -> list[str]:
        from .queries import EXACT_PRODUCT_ID_PATTERN
        if any(len(v) > 128 or not EXACT_PRODUCT_ID_PATTERN.fullmatch(v) for v in values):
            raise ValueError("商品 ID 无效")
        return list(dict.fromkeys(values))


class AssignGroup(ProductIds):
    groupId: UUID | None = None


class AssignGroupResponse(BaseModel):
    updated: list[str]
    groupId: UUID | None


class Capabilities(BaseModel):
    groupWrites: bool
    export: bool = True
    productEdit: bool = False
    importProducts: bool = False
    categoryLookup: bool = False
