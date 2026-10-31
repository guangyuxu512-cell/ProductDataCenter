from typing import Annotated, Literal
import os
from uuid import UUID

from fastapi import APIRouter, Depends, Request, Response
from fastapi.responses import FileResponse

from app.core.config import get_settings
from app.core.database.session import get_database_engine
from app.core.security.access import require_api_access, require_group_writes
from .repository import ProductRepository
from .service import ProductService
from .schemas import (AssignGroup, AssignGroupResponse, Capabilities, DeleteGroupResponse,
                      GroupName, GroupResponse, GroupsRead, ProductDetail, ProductIds, ProductPage)

router = APIRouter(prefix="/api/v1", tags=["product-library"], dependencies=[Depends(require_api_access)])


def get_service() -> ProductService:
    return ProductService(ProductRepository(get_database_engine()), get_settings())


Service = Annotated[ProductService, Depends(get_service)]


@router.get("/capabilities", response_model=Capabilities)
def capabilities():
    settings = get_settings()
    can_edit, can_create = False, False
    if settings.enable_product_edits:
        from app.modules.product_edit.repository import EditorRepository
        can_edit, can_create = EditorRepository(get_database_engine()).permissions()
    asset_ready = bool(can_edit and settings.product_asset_root and settings.product_asset_root.is_dir()
                       and os.access(settings.product_asset_root, os.W_OK))
    return Capabilities(groupWrites=settings.enable_group_writes, productEdit=can_edit,
                        manualCreate=can_create, assetUploads=asset_ready)


@router.get("/products", response_model=ProductPage)
def products(request: Request, service: Service):
    return service.list(request.query_params)


@router.get("/product-groups", response_model=GroupsRead)
def groups(service: Service):
    return service.groups()


@router.post("/product-groups", response_model=GroupResponse, dependencies=[Depends(require_group_writes)])
def create_group(body: GroupName, service: Service):
    return service.save_group(body.name)


@router.patch("/product-groups/{group_id}", response_model=GroupResponse, dependencies=[Depends(require_group_writes)])
def rename_group(group_id: UUID, body: GroupName, service: Service):
    return service.save_group(body.name, group_id)


@router.delete("/product-groups/{group_id}", response_model=DeleteGroupResponse, dependencies=[Depends(require_group_writes)])
def delete_group(group_id: UUID, service: Service):
    return service.delete_group(group_id)


@router.patch("/products/group", response_model=AssignGroupResponse, dependencies=[Depends(require_group_writes)])
def move_group(body: AssignGroup, service: Service):
    return service.assign_group(body.productIds, body.groupId)


@router.post("/products/export-uu")
def export_uu(body: ProductIds, service: Service):
    content, filename, count, missing = service.export(body.productIds)
    return Response(content=content, media_type="application/zip", headers={
        "Content-Disposition": f'attachment; filename="{filename}"',
        "X-Export-Count": str(count), "X-Export-Missing-Count": str(missing),
        "Cache-Control": "no-store", "X-Content-Type-Options": "nosniff",
    })


@router.post("/products/export-packages")
def export_packages(body: ProductIds, service: Service):
    content, filename, count, missing = service.export_packages(body.productIds)
    return Response(content=content, media_type="application/zip", headers={
        "Content-Disposition": f'attachment; filename="{filename}"',
        "X-Export-Count": str(count), "X-Export-Missing-Count": str(missing),
        "Cache-Control": "no-store", "X-Content-Type-Options": "nosniff",
    })


@router.get("/products/{product_id}", response_model=ProductDetail)
def detail(product_id: str, service: Service):
    return service.detail(product_id)


@router.get("/products/{product_id}/images/{kind}/{position}")
def image(product_id: str, kind: Literal["main", "detail", "sku"], position: int, service: Service):
    return FileResponse(service.image_file(product_id, kind, position),
                        headers={"Cache-Control": "private, max-age=60", "X-Content-Type-Options": "nosniff"})
