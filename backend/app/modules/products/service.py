from __future__ import annotations

from sqlalchemy.exc import IntegrityError

from app.core.config import Settings
from app.modules.product_images.urls import canonical_product_image_url
from .errors import GroupNameConflict, GroupNotFound, ProductNotFound
from .export import export_archive, resolve_data_file
from .queries import parse_product_list_options
from .repository import ProductRepository


class ProductService:
    def __init__(self, repository: ProductRepository, settings: Settings):
        self.repository = repository
        self.settings = settings

    def list(self, params):
        return self.list_options(parse_product_list_options(params))

    def list_options(self, options):
        page = self.repository.list(options)
        for item in page["items"]:
            item["main_image_url"] = self._image_url(item.get("main_image_url"))
        return page

    def detail(self, product_id: str):
        detail = self.repository.detail(product_id)
        if detail is None:
            raise ProductNotFound()
        detail["product"]["main_image_url"] = self._image_url(detail["product"].get("main_image_url"))
        detail["images"] = [{**dict(item), "source_url": self._image_url(item.get("source_url")) or ""}
                            for item in detail["images"]]
        return detail

    def _image_url(self, value):
        return canonical_product_image_url(value, self.settings.image_public_base_url,
                                           self.settings.image_legacy_base_urls)

    def edit_snapshot(self, product_id: str):
        return self.repository.edit_snapshot(product_id)

    def create_manual(self, title: str, draft_seed=None, edit=None):
        return {"productId": self.repository.create_manual(title, draft_seed, edit)}

    def save_edit(self, product_id: str, edit):
        return self.repository.save_edit(product_id, edit)

    def groups(self):
        return {"groups": self.repository.groups()}

    def save_group(self, name: str, group_id=None):
        try:
            with self.repository.engine.begin() as conn:
                group = self.repository.rename_group(conn, group_id, name) if group_id else self.repository.create_group(conn, name)
                if group is None:
                    raise GroupNotFound()
                return {"group": group}
        except IntegrityError as error:
            if getattr(error.orig, "sqlstate", None) == "23505":
                raise GroupNameConflict() from None
            raise

    def delete_group(self, group_id):
        with self.repository.engine.begin() as conn:
            group = self.repository.lock_group(conn, group_id)
            if group is None:
                raise GroupNotFound()
            count = self.repository.delete_group(conn, group_id)
            return {"deleted": {"groupId": group_id, "name": group["group_name"], "productCount": count}}

    def assign_group(self, product_ids: list[str], group_id):
        with self.repository.engine.begin() as conn:
            if group_id and self.repository.lock_group(conn, group_id) is None:
                raise GroupNotFound()
            updated = self.repository.assign_group(conn, product_ids, group_id)
            return {"updated": updated, "groupId": group_id}

    def delete_products(self, product_ids: list[str]):
        deleted = self.repository.delete_products(product_ids)
        removed = set(deleted)
        return {"deleted": deleted, "missing": [identity for identity in product_ids if identity not in removed]}

    def export(self, product_ids: list[str]):
        return export_archive(self.repository.export_rows(product_ids), product_ids,
                              self.settings.export_max_bytes, self.settings.image_public_base_url,
                              self.settings.image_legacy_base_urls)

    def image_file(self, product_id: str, kind: str, position: int):
        row = self.repository.image(product_id, kind, position)
        path = resolve_data_file(self.settings.data_root, row["rel_path"]) if row else None
        if path is None or path.suffix.lower() not in {".jpg", ".jpeg", ".png", ".webp", ".gif"}:
            raise ProductNotFound("本地图片不存在")
        return path
