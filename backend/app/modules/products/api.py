from dataclasses import replace
from typing import Annotated, Literal
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Request, Response
from fastapi.responses import FileResponse

from app.core.config import get_settings
from app.core.database.session import get_database_engine
from app.core.security.access import require_api_access, require_group_writes, require_product_writes, require_permission
from app.core.security.scoped_tokens import Principal
from .repository import ProductRepository
from .service import ProductService
from .errors import ProductNotFound
from .queries import parse_product_list_options
from .schemas import (AssignGroup, AssignGroupResponse, Capabilities, DeleteGroupResponse,
                      GroupName, GroupResponse, GroupsRead, ManualProductCreate, ProductDetail, ProductEdit, ProductIds, ProductPage)

router = APIRouter(prefix="/api/v1", tags=["product-library"], dependencies=[Depends(require_api_access)])


def get_service() -> ProductService:
    return ProductService(ProductRepository(get_database_engine()), get_settings())


Service = Annotated[ProductService, Depends(get_service)]
Actor = Annotated[Principal, Depends(require_api_access)]


def require_group(principal: Principal, group_id) -> None:
    value = str(group_id) if group_id is not None else "ungrouped"
    if principal.groups is not None and value not in principal.groups:
        raise HTTPException(403, "当前 Token 无权访问此分组")


@router.get("/capabilities", response_model=Capabilities)
def capabilities(principal: Annotated[Principal, Depends(require_api_access)]):
    settings = get_settings()
    can = principal.has
    return Capabilities(groupWrites=settings.enable_group_writes and all(can(p) for p in ("group.create", "group.update", "group.delete", "group.assign")),
                        productEdit=settings.enable_product_writes and all(can(p) for p in ("product.read", "product.create", "product.update", "product.delete", "image.upload")),
                        export=can("product.export"), categoryLookup=settings.douyin_category_lookup_enabled and can("category.read"),
                        autoPrecheck=settings.auto_precheck_enabled and can("precheck.read") and can("precheck.run"),
                        permissions=sorted(principal.permissions), groupIds=sorted(principal.groups) if principal.groups is not None else None)


@router.get("/products", response_model=ProductPage, dependencies=[Depends(require_permission("product.read"))])
def products(request: Request, service: Service, principal: Actor):
    if principal.groups is None:
        return service.list(request.query_params)
    options = replace(parse_product_list_options(request.query_params), allowed_groups=tuple(principal.groups))
    return service.list_options(options)


@router.post("/products", dependencies=[Depends(require_permission("product.create")), Depends(require_product_writes)])
def create_manual_product(body: ManualProductCreate, service: Service, principal: Actor):
    require_group(principal, body.groupId)
    if body.groupId is None:
        return service.create_manual(body.title, body.draftSeed, body.edit)
    return service.create_manual(body.title, body.draftSeed, body.edit, group_id=body.groupId)


@router.get("/product-groups", response_model=GroupsRead, dependencies=[Depends(require_permission("group.read"))])
def groups(service: Service, principal: Actor):
    return service.groups() if principal.groups is None else service.groups(allowed_groups=principal.groups)


@router.post("/product-groups", response_model=GroupResponse, dependencies=[Depends(require_permission("group.create")), Depends(require_group_writes)])
def create_group(body: GroupName, service: Service, principal: Actor):
    if principal.groups is not None:
        raise HTTPException(403, "限定分组的 Token 不能创建新分组")
    return service.save_group(body.name)


@router.patch("/product-groups/{group_id}", response_model=GroupResponse, dependencies=[Depends(require_permission("group.update")), Depends(require_group_writes)])
def rename_group(group_id: UUID, body: GroupName, service: Service, principal: Actor):
    require_group(principal, group_id)
    return service.save_group(body.name, group_id)


@router.delete("/product-groups/{group_id}", response_model=DeleteGroupResponse, dependencies=[Depends(require_permission("group.delete")), Depends(require_group_writes)])
def delete_group(group_id: UUID, service: Service, principal: Actor):
    require_group(principal, group_id)
    return service.delete_group(group_id)


@router.patch("/products/group", response_model=AssignGroupResponse, dependencies=[Depends(require_permission("group.assign")), Depends(require_group_writes)])
def move_group(body: AssignGroup, service: Service, principal: Actor):
    require_group(principal, body.groupId)
    return (service.assign_group(body.productIds, body.groupId) if principal.groups is None else
            service.assign_group(body.productIds, body.groupId, allowed_groups=principal.groups))


@router.post("/products/export-uu", dependencies=[Depends(require_permission("product.export"))])
def export_uu(body: ProductIds, service: Service, principal: Actor):
    content, filename, count, missing = (service.export(body.productIds) if principal.groups is None else
                                         service.export(body.productIds, allowed_groups=principal.groups))
    return Response(content=content, media_type="application/zip", headers={
        "Content-Disposition": f'attachment; filename="{filename}"',
        "X-Export-Count": str(count), "X-Export-Missing-Count": str(missing),
        "Cache-Control": "no-store", "X-Content-Type-Options": "nosniff",
    })


@router.post("/products/delete", dependencies=[Depends(require_permission("product.delete")), Depends(require_product_writes)])
def delete_products(body: ProductIds, service: Service, principal: Actor):
    return (service.delete_products(body.productIds) if principal.groups is None else
            service.delete_products(body.productIds, allowed_groups=principal.groups))


@router.get("/products/{product_id}", response_model=ProductDetail, dependencies=[Depends(require_permission("product.read"))])
def detail(product_id: str, service: Service, principal: Actor):
    return service.detail(product_id) if principal.groups is None else service.detail(product_id, allowed_groups=principal.groups)


@router.get("/products/{product_id}/edit", dependencies=[Depends(require_permission("product.update")), Depends(require_product_writes)])
def edit_snapshot(product_id: str, response: Response, service: Service, principal: Actor):
    response.headers["Cache-Control"] = "no-store"
    return service.edit_snapshot(product_id) if principal.groups is None else service.edit_snapshot(product_id, allowed_groups=principal.groups)


@router.patch("/products/{product_id}", dependencies=[Depends(require_permission("product.update")), Depends(require_product_writes)])
def save_product(product_id: str, body: ProductEdit, service: Service, principal: Actor):
    return (service.save_edit(product_id, body) if principal.groups is None else
            service.save_edit(product_id, body, allowed_groups=principal.groups))


@router.get("/products/{product_id}/images/{kind}/{position}", dependencies=[Depends(require_permission("product.read"))])
async def image(product_id: str, kind: Literal["main", "detail", "sku"], position: int, service: Service, principal: Actor):
    try:
        path = (service.image_file(product_id, kind, position) if principal.groups is None else
                service.image_file(product_id, kind, position, allowed_groups=principal.groups))
    except ProductNotFound:
        settings = service.settings
        if not (settings.image_remote_upload_origin and settings.image_remote_upload_token_file):
            raise
        row = (service.repository.image(product_id, kind, position) if principal.groups is None else
               service.repository.image(product_id, kind, position, allowed_groups=principal.groups))
        if not row or not row.get("rel_path"):
            raise
        from app.modules.product_images.remote_upload import read_source_image_from_nas
        return await read_source_image_from_nas(settings, row["rel_path"])
    return FileResponse(path, headers={"Cache-Control": "private, max-age=60", "X-Content-Type-Options": "nosniff"})
