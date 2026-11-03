from datetime import datetime
from decimal import Decimal
from typing import Literal
from uuid import UUID

from pydantic import BaseModel, Field, field_validator, model_validator


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


class SourceAttribute(BaseModel):
    id: str | None = None
    name: str
    values: list[str]


class TargetCategoryPart(BaseModel):
    id: str
    name: str


class ProductDetail(BaseModel):
    product: ProductRead
    skus: list[SkuRead]
    images: list[ImageRead]
    sourceCategoryId: str | None = None
    sourceAttributes: list[SourceAttribute] = Field(default_factory=list)
    targetCategory: list[TargetCategoryPart] = Field(default_factory=list)
    targetAttributes: list[SourceAttribute] = Field(default_factory=list)


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


class CategoryPart(BaseModel):
    id: str = Field(pattern=r"^[0-9]{1,20}$")
    name: str = Field(min_length=1, max_length=200)


class AttributeValueEdit(BaseModel):
    valueId: str = Field(default="0", max_length=200)
    name: str = Field(min_length=1, max_length=2000)


class AttributeEdit(BaseModel):
    id: str = Field(min_length=1, max_length=100)
    name: str = Field(min_length=1, max_length=200)
    values: list[AttributeValueEdit] = Field(max_length=30)


class SpecImageEdit(BaseModel):
    specId: str = Field(min_length=1, max_length=200)
    url: str = Field(default="", max_length=10000)

    @field_validator("url")
    @classmethod
    def valid_url(cls, value: str) -> str:
        from urllib.parse import urlsplit
        if value:
            parsed = urlsplit(value)
            if parsed.scheme not in {"http", "https"} or not parsed.hostname:
                raise ValueError("规格图片地址无效")
        return value


class SkuEdit(BaseModel):
    specIds: list[str] = Field(min_length=1, max_length=3)
    price: Decimal | None = Field(default=None, gt=0, le=9999999999, decimal_places=2)
    stock: int | None = Field(default=None, ge=0, le=2147483647)
    merchantCode: str | None = Field(default=None, max_length=200)
    enabled: bool | None = None
    delete: bool = False

    @field_validator("specIds")
    @classmethod
    def valid_spec_ids(cls, values: list[str]) -> list[str]:
        if any(not value or len(value) > 200 or "_" in value for value in values) or len(values) != len(set(values)):
            raise ValueError("SKU 规格标识无效")
        return values

    @model_validator(mode="after")
    def has_change(self):
        if not self.delete and all(value is None for value in (self.price, self.stock, self.merchantCode, self.enabled)):
            raise ValueError("SKU 没有需要保存的修改")
        return self


class StructureValue(BaseModel):
    id: str = Field(min_length=1, max_length=200)
    name: str = Field(min_length=1, max_length=200)
    url: str = Field(default="", max_length=10000)

    @field_validator("id")
    @classmethod
    def valid_id(cls, value: str) -> str:
        if "_" in value:
            raise ValueError("规格标识无效")
        return value

    @field_validator("name")
    @classmethod
    def valid_name(cls, value: str) -> str:
        value = value.strip()
        if not value:
            raise ValueError("规格名称不能为空")
        return value

    @field_validator("url")
    @classmethod
    def valid_url(cls, value: str) -> str:
        return SpecImageEdit.valid_url(value)


class StructureGroup(BaseModel):
    sourceIndex: int | None = Field(default=None, ge=0, le=2)
    name: str = Field(min_length=1, max_length=200)
    values: list[StructureValue] = Field(min_length=1, max_length=500)

    @field_validator("name")
    @classmethod
    def valid_name(cls, value: str) -> str:
        value = value.strip()
        if not value:
            raise ValueError("规格类型不能为空")
        return value


class StructureSku(BaseModel):
    sourceSpecIds: list[str] | None = Field(default=None, min_length=1, max_length=3)
    specIds: list[str] = Field(min_length=1, max_length=3)
    price: str = Field(default="", max_length=40)
    stock: str = Field(default="", max_length=20)
    merchantCode: str = Field(default="", max_length=200)
    enabled: bool | None = None

    @field_validator("sourceSpecIds", "specIds")
    @classmethod
    def valid_ids(cls, values: list[str] | None) -> list[str] | None:
        if values is not None and (any(not value or len(value) > 200 or "_" in value for value in values) or
                                   len(values) != len(set(values))):
            raise ValueError("SKU 规格标识无效")
        return values


class SpecStructureEdit(BaseModel):
    groups: list[StructureGroup] = Field(min_length=1, max_length=3)
    skus: list[StructureSku] = Field(min_length=1, max_length=2000)


class ProductEdit(BaseModel):
    expectedVersion: str = Field(pattern=r"^[a-f0-9]{64}$")
    title: str | None = Field(default=None, min_length=1, max_length=10000)
    category: list[CategoryPart] | None = Field(default=None, min_length=1, max_length=4)
    attributes: list[AttributeEdit] | None = Field(default=None, max_length=300)
    mainImages: list[str] | None = Field(default=None, max_length=100)
    detailImages: list[str] | None = Field(default=None, max_length=100)
    specImages: list[SpecImageEdit] | None = Field(default=None, max_length=500)
    specImageGroupIndex: int | None = Field(default=None, ge=1, le=2)
    skus: list[SkuEdit] | None = Field(default=None, max_length=2000)
    specStructure: SpecStructureEdit | None = None

    @field_validator("title")
    @classmethod
    def valid_title(cls, value: str | None) -> str | None:
        if value is None:
            return None
        value = value.strip()
        # Match the existing editor's platform counter (non-ASCII characters count twice).
        if not value or sum(2 if ord(character) > 127 else 1 for character in value) > 60:
            raise ValueError("商品标题不能为空，长度不能超过 60")
        return value

    @field_validator("mainImages", "detailImages")
    @classmethod
    def valid_images(cls, values: list[str] | None) -> list[str] | None:
        from urllib.parse import urlsplit
        if values is None:
            return None
        for value in values:
            parsed = urlsplit(value)
            if len(value) > 10000 or parsed.scheme not in {"http", "https"} or not parsed.hostname:
                raise ValueError("图片地址必须是有效的 HTTP 或 HTTPS 地址")
        return values

    @model_validator(mode="after")
    def valid_edit(self):
        if all(value is None for value in (self.title, self.category, self.attributes, self.mainImages, self.detailImages, self.specImages, self.specImageGroupIndex, self.skus, self.specStructure)):
            raise ValueError("没有需要保存的修改")
        if self.specStructure is not None and any(value is not None for value in (self.skus, self.specImages, self.specImageGroupIndex)):
            raise ValueError("规格结构和单项规格修改不能同时提交")
        if self.attributes is not None and len({item.id for item in self.attributes}) != len(self.attributes):
            raise ValueError("属性 ID 不能重复")
        if self.specImages is not None and len({item.specId for item in self.specImages}) != len(self.specImages):
            raise ValueError("规格 ID 不能重复")
        if self.skus is not None and len({tuple(item.specIds) for item in self.skus}) != len(self.skus):
            raise ValueError("SKU 规格组合不能重复")
        return self
