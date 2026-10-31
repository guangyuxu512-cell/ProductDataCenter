import hashlib
import os
from concurrent.futures import ThreadPoolExecutor
from threading import Barrier

import pytest
from fastapi.testclient import TestClient

from app.core.config import get_settings
from app.main import create_application
from app.modules.source_categories.pdd import InvalidCategoryDictionary, parse_dictionary
from app.modules.source_categories import pdd as category_module
from app.modules.source_categories import service as category_service


HEADER = "id,name,parent_id,level,is_leaf,path_ids,path_names,is_hidden,is_deleted\n"
ROOT = "239,男装,0,1,False,239,男装,0,0\n"
LEAF = "245,衬衫,239,2,True,239 > 245,男装 > 衬衫,0,0\n"
CSV = (HEADER + ROOT + LEAF).encode()
ADMIN = {"Authorization": "Bearer admin-test-token"}
RPA = {"Authorization": "Bearer rpa-test-token"}


def test_dictionary_returns_source_path_and_content_version():
    dictionary = parse_dictionary(CSV)
    item = dictionary.get("245")
    assert item is not None
    assert item.path_ids == ("239", "245")
    assert item.path_names == ("男装", "衬衫")
    assert item.is_leaf and not item.is_deleted and not item.is_hidden
    assert dictionary.sha256 == hashlib.sha256(CSV).hexdigest()
    assert dictionary.get("999") is None
    with pytest.raises(TypeError):
        dictionary.categories["999"] = item


@pytest.mark.parametrize("content", [
    b"", b"\xff", HEADER.encode(),
    (HEADER + ROOT + LEAF + LEAF).encode(),
    (HEADER + LEAF).encode(),
    (HEADER + ROOT + LEAF.replace("239 > 245", "123 > 245")).encode(),
    (HEADER + ROOT + LEAF.replace("男装 > 衬衫", "女装 > 衬衫")).encode(),
    (HEADER + ROOT + LEAF.replace("True", "maybe")).encode(),
    (HEADER + ROOT.replace("False", "True") + LEAF).encode(),
    (HEADER + ROOT + LEAF.replace("衬衫,239,2", "衬衫,239,3")).encode(),
])
def test_invalid_or_incomplete_dictionary_is_rejected(content):
    with pytest.raises(InvalidCategoryDictionary):
        parse_dictionary(content)


@pytest.fixture
def client(monkeypatch, tmp_path):
    path = tmp_path / "pdd_categories.csv"
    path.write_bytes(CSV)
    monkeypatch.setenv("BACKEND_API_TOKEN", "admin-test-token")
    monkeypatch.setenv("BACKEND_RPA_API_TOKEN", "rpa-test-token")
    monkeypatch.setenv("BACKEND_ENABLE_PRODUCT_EDITS", "false")
    monkeypatch.setenv("BACKEND_ENABLE_SOURCE_CATEGORY_READS", "true")
    monkeypatch.setenv("BACKEND_PDD_CATEGORY_CSV", str(path))
    monkeypatch.setenv("BACKEND_PDD_CATEGORY_SHA256", hashlib.sha256(CSV).hexdigest())
    monkeypatch.delenv("BACKEND_API_TOKEN_FILE", raising=False)
    monkeypatch.delenv("BACKEND_RPA_API_TOKEN_FILE", raising=False)
    get_settings.cache_clear()
    with TestClient(create_application()) as test_client:
        yield test_client, path
    get_settings.cache_clear()


def test_source_category_api_is_admin_only_and_never_returns_target_category(client, monkeypatch):
    http, _path = client
    endpoint = "/api/v1/source-categories/pinduoduo/245"
    unauthorized = http.get(endpoint)
    assert unauthorized.status_code == 401 and unauthorized.headers["cache-control"] == "no-store"
    assert http.get(endpoint, headers=RPA).status_code == 401
    response = http.get(endpoint, headers=ADMIN)
    assert response.status_code == 200
    assert response.headers["cache-control"] == "no-store"
    assert response.json() == {
        "sourcePlatform": "pinduoduo", "categoryId": "245", "isLeaf": True,
        "path": [
            {"id": "239", "name": "男装", "isHidden": False, "isDeleted": False},
            {"id": "245", "name": "衬衫", "isHidden": False, "isDeleted": False},
        ],
        "dictionarySha256": hashlib.sha256(CSV).hexdigest(),
    }
    for missing in ("999", "not-an-id"):
        response = http.get(f"/api/v1/source-categories/pinduoduo/{missing}", headers=ADMIN)
        assert response.status_code == 404 and response.headers["cache-control"] == "no-store"
    assert http.post("/api/v1/products/manual", headers=ADMIN, json={"title": "商品"}).status_code == 403
    monkeypatch.setenv("BACKEND_ENABLE_SOURCE_CATEGORY_READS", "false")
    get_settings.cache_clear()
    response = http.get(endpoint, headers=ADMIN)
    assert response.status_code == 403 and response.headers["cache-control"] == "no-store"


def test_replacing_dictionary_requires_new_approved_checksum(client, tmp_path, monkeypatch):
    http, path = client
    endpoint = "/api/v1/source-categories/pinduoduo/245"
    previous = http.get(endpoint, headers=ADMIN).json()
    updated = CSV.replace("衬衫".encode(), "新衬衫".encode())
    replacement = tmp_path / "replacement.csv"
    replacement.write_bytes(updated)
    os.replace(replacement, path)
    response = http.get(endpoint, headers=ADMIN)
    assert response.status_code == 503
    assert response.headers["cache-control"] == "no-store"
    assert response.json()["code"] == "PDD_CATEGORY_DICTIONARY_UNAVAILABLE"
    monkeypatch.setenv("BACKEND_PDD_CATEGORY_SHA256", hashlib.sha256(updated).hexdigest())
    get_settings.cache_clear()
    response = http.get(endpoint, headers=ADMIN)
    assert response.status_code == 200
    assert response.json()["path"][-1]["name"] == "新衬衫"
    assert response.json()["dictionarySha256"] != previous["dictionarySha256"]
    path.write_bytes(b"invalid")
    response = http.get(endpoint, headers=ADMIN)
    assert response.status_code == 503
    assert response.json()["code"] == "PDD_CATEGORY_DICTIONARY_UNAVAILABLE"
    path.unlink()
    assert http.get(endpoint, headers=ADMIN).status_code == 503


def test_self_consistent_subset_is_not_accepted_as_approved_dictionary(client, monkeypatch):
    http, path = client
    complete = CSV + "300,女装,0,1,True,300,女装,0,0\n".encode()
    path.write_bytes(complete)
    monkeypatch.setenv("BACKEND_PDD_CATEGORY_SHA256", hashlib.sha256(complete).hexdigest())
    get_settings.cache_clear()
    endpoint = "/api/v1/source-categories/pinduoduo/245"
    assert http.get(endpoint, headers=ADMIN).status_code == 200
    # This subset is internally valid but is not the approved complete file.
    path.write_bytes(CSV)
    response = http.get(endpoint, headers=ADMIN)
    assert response.status_code == 503
    assert response.json()["code"] == "PDD_CATEGORY_DICTIONARY_UNAVAILABLE"


def test_missing_or_invalid_approved_checksum_fails_closed(client, monkeypatch):
    http, _path = client
    endpoint = "/api/v1/source-categories/pinduoduo/245"
    for value in (None, "", "0" * 64, "INVALID"):
        if value is None:
            monkeypatch.delenv("BACKEND_PDD_CATEGORY_SHA256", raising=False)
        else:
            monkeypatch.setenv("BACKEND_PDD_CATEGORY_SHA256", value)
        get_settings.cache_clear()
        response = http.get(endpoint, headers=ADMIN)
        assert response.status_code == 503
        assert response.json()["code"] == "PDD_CATEGORY_DICTIONARY_UNAVAILABLE"


def test_shared_or_unreadable_rpa_credential_never_grants_source_access(client, monkeypatch, tmp_path):
    http, _path = client
    endpoint = "/api/v1/source-categories/pinduoduo/245"
    monkeypatch.setenv("BACKEND_RPA_API_TOKEN", "admin-test-token")
    get_settings.cache_clear()
    response = http.get(endpoint, headers=ADMIN)
    assert response.status_code == 503
    assert response.json()["code"] == "SOURCE_CATEGORY_ACCESS_MISCONFIGURED"
    monkeypatch.delenv("BACKEND_RPA_API_TOKEN")
    monkeypatch.setenv("BACKEND_RPA_API_TOKEN_FILE", str(tmp_path / "missing-token"))
    get_settings.cache_clear()
    assert http.get(endpoint, headers=ADMIN).status_code == 503


def test_concurrent_cold_load_and_replacement_parse_each_version_once(tmp_path, monkeypatch):
    path = tmp_path / "categories.csv"
    path.write_bytes(CSV)
    category_module._read_cached.cache_clear()
    real_parse = category_module.parse_dictionary
    calls = []

    def record_parse(content):
        calls.append(hashlib.sha256(content).hexdigest())
        return real_parse(content)

    monkeypatch.setattr(category_module, "parse_dictionary", record_parse)

    def concurrent_read():
        barrier = Barrier(8)

        def lookup():
            barrier.wait(timeout=5)
            return category_module.read_dictionary(path)

        with ThreadPoolExecutor(max_workers=8) as pool:
            return list(pool.map(lambda _index: lookup(), range(8)))

    initial = concurrent_read()
    assert len(calls) == 1 and all(item is initial[0] for item in initial)
    replacement = tmp_path / "new.csv"
    replacement.write_bytes(CSV.replace("衬衫".encode(), "新衬衫".encode()))
    os.replace(replacement, path)
    updated = concurrent_read()
    assert len(calls) == 2 and all(item is updated[0] for item in updated)
    assert updated[0].sha256 != initial[0].sha256


def test_unexpected_source_error_is_sanitized_and_not_cached(client, monkeypatch):
    def broken(_path):
        raise RuntimeError("synthetic-private-diagnostic")

    monkeypatch.setattr(category_service, "read_dictionary", broken)
    with TestClient(create_application(), raise_server_exceptions=False) as http:
        response = http.get("/api/v1/source-categories/pinduoduo/245", headers=ADMIN)
    assert response.status_code == 500
    assert response.headers["cache-control"] == "no-store"
    assert "synthetic-private-diagnostic" not in response.text


def test_unrelated_unexpected_error_retains_existing_error_contract(client):
    app = create_application()

    @app.get("/synthetic-error")
    def fail():
        raise RuntimeError("synthetic-private-diagnostic")

    with TestClient(app, raise_server_exceptions=False) as http:
        response = http.get("/synthetic-error")
    assert response.status_code == 500
    assert response.json()["code"] == "INTERNAL_ERROR"
    assert "synthetic-private-diagnostic" not in response.text
    assert "cache-control" not in response.headers
