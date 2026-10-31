from __future__ import annotations

import re
from typing import Literal
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator


def validate_title(value: str) -> str:
    if not value.strip():
        raise ValueError("请输入商品标题")
    # 与用户提供的抖店页面计数一致：ASCII 算一位，非 ASCII 算两位。
    if sum(1 if ord(character) <= 127 else 2 for character in value) > 60:
        raise ValueError("商品标题不能超过 60 个计数单位")
    return value


class EditModel(BaseModel):
    model_config = ConfigDict(extra="forbid")


class ImageItem(EditModel):
    id: str = Field(min_length=1, max_length=128)
    url: str = Field(default="", max_length=4096)


class SpecValue(EditModel):
    id: str = Field(min_length=1, max_length=128)
    sourceValueId: str | None = Field(default=None, max_length=128)
    name: str = Field(default="", max_length=200)
    imageUrl: str = Field(default="", max_length=4096)


class SpecDimension(EditModel):
    id: str = Field(min_length=1, max_length=128)
    name: str = Field(default="", max_length=120)
    values: list[SpecValue] = Field(default_factory=list, max_length=200)


class SkuDraft(EditModel):
    id: str = Field(min_length=1, max_length=128)
    sourceSkuId: str | None = Field(default=None, max_length=128)
    sourceLabel: str = Field(default="", max_length=500)
    sourceStatusRaw: str | None = Field(default=None, max_length=128)
    specValueIds: dict[str, str] = Field(default_factory=dict, max_length=8)
    unmappedSpecIds: list[str] = Field(default_factory=list, max_length=16)
    price: str | None = Field(default=None, max_length=24)
    stock: int | None = Field(default=None, strict=True, ge=0, le=2_147_483_647)
    merchantCode: str = Field(default="", max_length=128)
    state: Literal["active", "inactive", "unknown"] = "unknown"

    @field_validator("price")
    @classmethod
    def valid_price(cls, value: str | None) -> str | None:
        if value is None or value == "":
            return None
        if not re.fullmatch(r"\d{1,10}(?:\.\d{1,2})?", value, re.ASCII):
            raise ValueError("SKU 价格应为非负数字，最多保留两位小数")
        return value


class AttributeValue(EditModel):
    id: str = Field(default="", max_length=128)
    name: str = Field(default="", max_length=500)


class ProductAttribute(EditModel):
    id: str = Field(min_length=1, max_length=128)
    name: str = Field(default="", max_length=200)
    values: list[AttributeValue] = Field(default_factory=list, max_length=100)


class ProductDraft(EditModel):
    title: str = Field(default="", max_length=1000)
    categoryIds: list[str] = Field(default_factory=list, max_length=4)
    categoryPath: str = Field(default="", max_length=1000)
    mainImages: list[ImageItem] = Field(default_factory=list, max_length=100)
    detailImages: list[ImageItem] = Field(default_factory=list, max_length=100)
    attributes: list[ProductAttribute] = Field(default_factory=list, max_length=300)
    dimensions: list[SpecDimension] = Field(default_factory=list, max_length=8)
    imageDimensionId: str | None = Field(default=None, max_length=128)
    skus: list[SkuDraft] = Field(default_factory=list, max_length=2000)

    @model_validator(mode="after")
    def valid_identities(self):
        dimension_ids = [item.id for item in self.dimensions]
        value_ids = [value.id for dimension in self.dimensions for value in dimension.values]
        sku_ids = [sku.id for sku in self.skus]
        image_ids = [item.id for item in self.mainImages + self.detailImages]
        attribute_ids = [item.id for item in self.attributes]
        for label, ids in (("规格类型", dimension_ids), ("规格值", value_ids),
                           ("SKU", sku_ids), ("图片", image_ids), ("属性", attribute_ids)):
            if len(ids) != len(set(ids)):
                raise ValueError(f"{label}标识重复")
        if self.imageDimensionId is not None and (
            not self.dimensions or self.dimensions[0].id != self.imageDimensionId
        ):
            raise ValueError("只有第一组规格可以启用规格图")
        return self


class SaveDraft(EditModel):
    expectedRevision: int = Field(strict=True, ge=0)
    sourceFingerprint: str = Field(pattern=r"^[0-9a-f]{64}$")
    draft: ProductDraft

    @model_validator(mode="after")
    def valid_title(self):
        validate_title(self.draft.title)
        return self


class CreateManualProduct(EditModel):
    title: str = Field(min_length=1, max_length=1000)
    groupId: UUID | None = None

    @field_validator("title")
    @classmethod
    def valid_title(cls, value: str) -> str:
        return validate_title(value.strip())


class EditorState(EditModel):
    productId: str
    revision: int
    sourceFingerprint: str
    sourceChanged: bool
    draft: ProductDraft
