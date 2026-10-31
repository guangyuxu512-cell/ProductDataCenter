import hashlib
import io
import json
import re
from datetime import datetime, timezone
from pathlib import Path
from zipfile import ZIP_STORED, ZipFile

from .errors import ExportUnavailable


def resolve_data_file(root: Path, relative: str) -> Path | None:
    base = root.resolve()
    candidate = (base / relative).resolve()
    if not relative or candidate == base or not candidate.is_relative_to(base):
        return None
    return candidate if candidate.is_file() else None


def current_uu_bytes(row: dict, root: Path, remaining: int) -> tuple[bytes, str]:
    candidate = resolve_data_file(root, row.get("uu_rel_path") or "")
    if candidate:
        if candidate.stat().st_size > remaining:
            raise ExportUnavailable("导出资料过大，请减少商品数量")
        content = candidate.read_bytes()
        expected = str(row.get("uu_sha256") or "").strip()
        if expected and hashlib.sha256(content).hexdigest() != expected:
            raise ExportUnavailable("商品数据包校验不一致，请核对资料后重试")
        source = "version_file"
    else:
        content, source = str(row["uu_text"]).encode("utf-8"), "database"
    if len(content) > remaining:
        raise ExportUnavailable("导出资料过大，请减少商品数量")
    try:
        json.loads(content)
    except (ValueError, UnicodeError):
        raise ExportUnavailable("商品数据包格式异常，无法导出") from None
    return content, source


def export_archive(rows: list[dict], product_ids: list[str], root: Path, max_bytes: int, *, legacy_names: bool = True):
    archive = io.BytesIO()
    exported: list[dict] = []
    total_bytes = 0
    now = datetime.now(timezone.utc)
    with ZipFile(archive, "w", compression=ZIP_STORED) as zipped:
        for row in rows:
            content, source = current_uu_bytes(row, root, max_bytes - total_bytes)
            total_bytes += len(content)
            platform = re.sub(r"[^a-zA-Z0-9_-]", "_", row["source_platform"])
            identity = re.sub(r"[^a-zA-Z0-9_-]", "_", row["source_product_id"] or row["product_id"])
            filename = f"UU/{platform}_{identity}_UU.txt" if legacy_names else f"product-packages/{platform}_{identity}.json"
            zipped.writestr(filename, content)
            entry = {"productId": row["product_id"], "sourcePlatform": row["source_platform"],
                "sourceProductId": row["source_product_id"] or row["product_id"], "title": row["title"],
                "capturedAt": row["captured_at"].isoformat() if row["captured_at"] else None,
                "filename": filename, "source": source, "sha256": hashlib.sha256(content).hexdigest(),
                ("storedUuSha256" if legacy_names else "storedSourceSha256"): str(row.get("uu_sha256") or "")}
            exported.append(entry)
        if not exported:
            raise ExportUnavailable("所选商品没有可导出的完整商品数据包")
        exported_ids = {item["productId"] for item in exported}
        missing = [identity for identity in product_ids if identity not in exported_ids]
        zipped.writestr("manifest.json", json.dumps({"schemaVersion": 1, "exportedAt": now.isoformat(),
            "requestedCount": len(product_ids), "exportedCount": len(exported),
            "missingProductIds": missing, "products": exported}, ensure_ascii=False, indent=2))
    prefix = "uu-export" if legacy_names else "product-packages"
    return archive.getvalue(), f"{prefix}-{now:%Y%m%d-%H%M%S}.zip", len(exported), len(missing)
