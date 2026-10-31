from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException

from app.core.database.session import get_database_engine
from app.core.security.access import require_api_access, require_group_writes, require_product_edits
from app.modules.products.errors import ProductNotFound
from app.modules.products.queries import EXACT_PRODUCT_ID_PATTERN
from .models import CreateManualProduct, EditorState, SaveDraft
from .repository import EditorRepository

router = APIRouter(prefix="/api/v1", tags=["product-edit"],
                   dependencies=[Depends(require_api_access), Depends(require_product_edits)])


def get_editor_repository() -> EditorRepository:
    return EditorRepository(get_database_engine())


Editor = Annotated[EditorRepository, Depends(get_editor_repository)]


def _allowed(repository: EditorRepository, *, create: bool = False) -> None:
    edit, manual = repository.permissions()
    if not (manual if create else edit):
        raise HTTPException(503, "商品编辑数据库结构或权限尚未就绪")


def _valid_id(product_id: str) -> None:
    if len(product_id) > 128 or not EXACT_PRODUCT_ID_PATTERN.fullmatch(product_id):
        raise ProductNotFound()


@router.get("/products/{product_id}/edit-draft", response_model=EditorState)
def read_draft(product_id: str, repository: Editor):
    _valid_id(product_id)
    _allowed(repository)
    return repository.read(product_id)


@router.put("/products/{product_id}/edit-draft", response_model=EditorState)
def save_draft(product_id: str, body: SaveDraft, repository: Editor):
    _valid_id(product_id)
    _allowed(repository)
    return repository.save(product_id, body)


@router.post("/products/manual", response_model=EditorState, status_code=201)
def create_manual(body: CreateManualProduct, repository: Editor):
    _allowed(repository, create=True)
    if body.groupId is not None:
        require_group_writes()
    return repository.create_manual(body.title, body.groupId)
