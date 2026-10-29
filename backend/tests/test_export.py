import hashlib
import io
import json
from pathlib import Path
from zipfile import ZipFile

import pytest

from app.modules.products.errors import ExportUnavailable
from app.modules.products.export import export_archive, resolve_data_file


def row(**overrides):
    return {"product_id": "3760269504500859111", "source_platform": "douyin",
            "source_product_id": "3760269504500859111", "title": "测试商品", "captured_at": None,
            "uu_rel_path": "", "uu_sha256": "", "uu_text": '{"goodsInfo": {"productId":"3760269504500859111"}}', **overrides}


def test_export_preserves_original_file_bytes_and_reports_missing(tmp_path):
    content = '{\r\n  "标题": "测试商品", "id": "3760269504500859111"\r\n}\r\n'.encode()
    (tmp_path / "version.txt").write_bytes(content)
    product = row(uu_rel_path="version.txt", uu_sha256=hashlib.sha256(content).hexdigest())
    data, _, count, missing = export_archive([product], [product["product_id"], "3837817973876326524"], tmp_path, 100000)
    assert (count, missing) == (1, 1)
    with ZipFile(io.BytesIO(data)) as archive:
        manifest = json.loads(archive.read("manifest.json"))
        entry = manifest["products"][0]
        assert archive.read(entry["filename"]) == content
        assert entry["sha256"] == product["uu_sha256"]
        assert entry["source"] == "version_file"


def test_database_fallback_is_explicit(tmp_path):
    product = row(uu_rel_path="missing.txt")
    data, *_ = export_archive([product], [product["product_id"]], tmp_path, 100000)
    with ZipFile(io.BytesIO(data)) as archive:
        entry = json.loads(archive.read("manifest.json"))["products"][0]
        assert entry["source"] == "database"
        assert archive.read(entry["filename"]) == product["uu_text"].encode()


def test_rejects_changed_file_and_oversize(tmp_path):
    (tmp_path / "version.txt").write_text('{}')
    with pytest.raises(ExportUnavailable, match="校验"):
        export_archive([row(uu_rel_path="version.txt", uu_sha256="0" * 64)], ["3760269504500859111"], tmp_path, 1000)
    with pytest.raises(ExportUnavailable, match="过大"):
        export_archive([row()], ["3760269504500859111"], tmp_path, 1)


def test_data_path_does_not_escape_root(tmp_path):
    root = tmp_path / "data"; root.mkdir()
    outside = tmp_path / "secret.txt"; outside.write_text('secret')
    (root / "symlink.txt").symlink_to(outside)
    assert resolve_data_file(root, "../secret.txt") is None
    assert resolve_data_file(root, str(outside)) is None
    assert resolve_data_file(root, "symlink.txt") is None
