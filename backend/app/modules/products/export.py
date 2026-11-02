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


def current_uu_bytes(row: dict, remaining: int) -> tuple[bytes, str]:
    # The database is the single source of the current package. Historical files
    # can remain on disk but must never override an edited database value.
    value = row.get("uu_text")
    if not isinstance(value, str) or not value:
        raise ExportUnavailable("商品数据包缺失，无法导出")
    content = value.encode("utf-8")
    if len(content) > remaining:
        raise ExportUnavailable("导出资料过大，请减少商品数量")
    try:
        json.loads(content)
    except (ValueError, UnicodeError):
        raise ExportUnavailable("UU 数据格式异常，无法导出") from None
    return content, "database"


def export_archive(rows: list[dict], product_ids: list[str], max_bytes: int):
    archive = io.BytesIO()
    exported: list[dict] = []
    total_bytes = 0
    now = datetime.now(timezone.utc)
    with ZipFile(archive, "w", compression=ZIP_STORED) as zipped:
        for row in rows:
            content, source = current_uu_bytes(row, max_bytes - total_bytes)
            total_bytes += len(content)
            platform = re.sub(r"[^a-zA-Z0-9_-]", "_", row["source_platform"])
            identity = re.sub(r"[^a-zA-Z0-9_-]", "_", row["source_product_id"] or row["product_id"])
            filename = f"UU/{platform}_{identity}_UU.txt"
            zipped.writestr(filename, content)
            exported.append({"productId": row["product_id"], "sourcePlatform": row["source_platform"],
                "sourceProductId": row["source_product_id"] or row["product_id"], "title": row["title"],
                "capturedAt": row["captured_at"].isoformat() if row["captured_at"] else None,
                "filename": filename, "source": source, "sha256": hashlib.sha256(content).hexdigest(),
                "storedUuSha256": str(row.get("uu_sha256") or "")})
        if not exported:
            raise ExportUnavailable("所选商品没有可导出的完整 UU")
        exported_ids = {item["productId"] for item in exported}
        missing = [identity for identity in product_ids if identity not in exported_ids]
        zipped.writestr("manifest.json", json.dumps({"schemaVersion": 1, "exportedAt": now.isoformat(),
            "requestedCount": len(product_ids), "exportedCount": len(exported),
            "missingProductIds": missing, "products": exported}, ensure_ascii=False, indent=2))
    return archive.getvalue(), f"uu-export-{now:%Y%m%d-%H%M%S}.zip", len(exported), len(missing)
