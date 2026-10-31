"""Read source categories only; target-category selection belongs to precheck."""

from secrets import compare_digest
from typing import Annotated, Literal

from fastapi import APIRouter, Depends, HTTPException
from fastapi.security import HTTPAuthorizationCredentials
from pydantic import BaseModel

from app.core.config import get_settings
from app.core.exceptions.errors import AppError
from app.core.security.access import bearer, require_api_access
from app.modules.source_categories.service import PddSourceCategoryService


class SourceCategoryAccessMisconfigured(AppError):
    code = "SOURCE_CATEGORY_ACCESS_MISCONFIGURED"
    message = "来源类目服务凭据配置不可用"
    status_code = 503


def reject_rpa_credential(
    credentials: Annotated[HTTPAuthorizationCredentials | None, Depends(bearer)],
) -> None:
    # Even an accidental shared token must not grant the read-only RPA
    # principal the management-only source dictionary endpoint.
    try:
        rpa_token = get_settings().configured_rpa_token()
    except (OSError, UnicodeError):
        raise SourceCategoryAccessMisconfigured() from None
    if credentials and rpa_token and compare_digest(
        credentials.credentials.encode(), rpa_token.encode(),
    ):
        raise SourceCategoryAccessMisconfigured()


def require_source_category_reads() -> None:
    if not get_settings().enable_source_category_reads:
        raise HTTPException(403, "当前商品服务未启用来源类目查询")


router = APIRouter(
    prefix="/api/v1/source-categories",
    tags=["source-categories"],
    dependencies=[Depends(require_api_access), Depends(reject_rpa_credential), Depends(require_source_category_reads)],
)


class SourceCategoryLevel(BaseModel):
    id: str
    name: str
    isHidden: bool
    isDeleted: bool


class SourceCategoryRead(BaseModel):
    sourcePlatform: Literal["pinduoduo"] = "pinduoduo"
    categoryId: str
    path: list[SourceCategoryLevel]
    isLeaf: bool
    dictionarySha256: str


def get_source_category_service() -> PddSourceCategoryService:
    settings = get_settings()
    return PddSourceCategoryService(settings.pdd_category_csv, settings.pdd_category_sha256)


CategoryService = Annotated[PddSourceCategoryService, Depends(get_source_category_service)]


@router.get("/pinduoduo/{category_id}", response_model=SourceCategoryRead)
def get_pdd_source_category(category_id: str, service: CategoryService) -> SourceCategoryRead:
    result = service.get(category_id)
    return SourceCategoryRead(
        categoryId=result.category.category_id,
        path=[SourceCategoryLevel(
            id=part.category_id, name=part.name,
            isHidden=part.is_hidden, isDeleted=part.is_deleted,
        ) for part in result.path],
        isLeaf=result.category.is_leaf,
        dictionarySha256=result.dictionary_sha256,
    )
