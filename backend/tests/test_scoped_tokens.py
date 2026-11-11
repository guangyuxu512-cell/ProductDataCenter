import json
import sqlite3
import subprocess
import sys
import time
from uuid import UUID

import pytest
from fastapi.testclient import TestClient

from app.core.config import get_settings
from app.main import create_application
from app.modules.products.api import get_service
from app.modules.products.service import ProductService


GROUP_A = "482f31fa-bb52-495e-b479-05eb10ebe532"
GROUP_B = "d25215ae-0271-4d07-963a-8c8647d60471"
PRODUCT = "3760269504500859111"
ADMIN = {"Authorization": "Bearer legacy-admin-test"}
RPA = {"Authorization": "Bearer legacy-rpa-test"}


class Repository:
    def list(self, options):
        row = {"product_id": PRODUCT, "source_platform": "douyin", "title": "测试商品", "group_id": GROUP_A}
        rows = [row] if options.allowed_groups is None or GROUP_A in options.allowed_groups else []
        return {"items": rows, "total": len(rows), "totalIncluded": True, "limit": options.limit, "offset": options.offset}

    def groups(self, allowed_groups=None):
        rows = [{"groupId": UUID(GROUP_A), "name": "A", "productCount": 1},
                {"groupId": UUID(GROUP_B), "name": "B", "productCount": 0}]
        return rows if allowed_groups is None else [row for row in rows if str(row["groupId"]) in allowed_groups]

    def group_exists(self, group_id):
        return str(group_id) in {GROUP_A, GROUP_B}

    def edit_snapshot(self, product_id, allowed_groups=None):
        return {"version": "a" * 64}

    def export_rows(self, ids, allowed_groups=None):
        if ids != [PRODUCT] or allowed_groups is not None and GROUP_A not in allowed_groups:
            return []
        return [{"product_id": PRODUCT, "source_platform": "douyin", "uu_text": '{"goodsId":"test"}'}]


@pytest.fixture
def client(monkeypatch, tmp_path):
    monkeypatch.setenv("BACKEND_API_TOKEN", "legacy-admin-test")
    monkeypatch.setenv("BACKEND_RPA_API_TOKEN", "legacy-rpa-test")
    monkeypatch.setenv("BACKEND_ENABLE_PRODUCT_WRITES", "true")
    monkeypatch.setenv("BACKEND_ENABLE_GROUP_WRITES", "true")
    monkeypatch.setenv("BACKEND_AUTO_PRECHECK_ENABLED", "false")
    monkeypatch.setenv("BACKEND_SCOPED_TOKEN_STORE_FILE", str(tmp_path / "private-tokens.sqlite3"))
    monkeypatch.delenv("BACKEND_API_TOKEN_FILE", raising=False)
    monkeypatch.delenv("BACKEND_RPA_API_TOKEN_FILE", raising=False)
    get_settings.cache_clear()
    app = create_application()
    app.dependency_overrides[get_service] = lambda: ProductService(Repository(), get_settings())
    with TestClient(app) as test_client:
        yield test_client, tmp_path / "private-tokens.sqlite3"
    get_settings.cache_clear()


def issue(client, *, name="test", permissions=None, groups=None, expiry=None, actor=ADMIN):
    response = client.post("/api/v1/tokens", headers=actor, json={"name": name,
        "permissions": permissions or ["product.read"], "groupIds": groups, "expiresAt": expiry})
    assert response.status_code == 201, response.text
    return response.json()


def bearer(secret):
    return {"Authorization": "Bearer " + secret}


def test_create_modify_and_revoke_applies_immediately_without_exposing_secret(client):
    c, path = client
    issued = issue(c, permissions=["product.read", "group.read"], groups=[GROUP_A])
    secret, token_id = issued["token"], issued["record"]["id"]
    scoped = bearer(secret)
    assert c.get("/api/v1/products", headers=scoped).json()["total"] == 1
    assert [x["name"] for x in c.get("/api/v1/product-groups", headers=scoped).json()["groups"]] == ["A"]
    assert c.get(f"/api/v1/products/{PRODUCT}/edit", headers=scoped).status_code == 403
    assert c.post("/api/v1/products/delete", headers=scoped, json={"productIds": [PRODUCT]}).status_code == 403
    assert c.post("/api/v1/product-images", headers=scoped, content=b"x").status_code == 403
    listed = c.get("/api/v1/tokens", headers=ADMIN)
    assert listed.status_code == 200 and secret not in listed.text
    assert listed.headers["cache-control"] == "no-store"
    assert secret.encode() not in path.read_bytes()
    with sqlite3.connect(path) as db:
        assert db.execute("SELECT action FROM scoped_token_events").fetchall() == [("create",)]
    changed = c.patch(f"/api/v1/tokens/{token_id}", headers=ADMIN,
                      json={"permissions": ["product.read", "group.read", "product.update"]})
    assert changed.status_code == 200 and secret not in changed.text
    assert c.get(f"/api/v1/products/{PRODUCT}/edit", headers=scoped).status_code == 200
    assert c.delete(f"/api/v1/tokens/{token_id}", headers=ADMIN).status_code == 204
    assert c.get("/api/v1/products", headers=scoped).status_code == 401
    assert c.get("/api/v1/products", headers=ADMIN).status_code == 200
    assert c.get("/rpa/v1/product-groups", headers=RPA).status_code == 200


def test_delegation_never_grants_more_and_parent_revoke_disables_child(client):
    c, _ = client
    expiry = int(time.time()) + 3600
    parent = issue(c, permissions=["token.create", "token.read", "token.update", "token.revoke", "product.read"],
                   groups=[GROUP_A], expiry=expiry)
    parent_auth = bearer(parent["token"])
    def create_body(**override):
        return {"name": "child", "permissions": ["product.read"], "groupIds": [GROUP_A], "expiresAt": expiry, **override}
    assert c.post("/api/v1/tokens", headers=parent_auth, json=create_body(permissions=["product.delete"])).status_code == 403
    assert c.post("/api/v1/tokens", headers=parent_auth, json=create_body(groupIds=[GROUP_B])).status_code == 403
    assert c.post("/api/v1/tokens", headers=parent_auth, json=create_body(expiresAt=expiry + 1)).status_code == 403
    assert c.post("/api/v1/tokens", headers=parent_auth, json=create_body(expiresAt=None)).status_code == 403
    assert c.post("/api/v1/tokens", headers=parent_auth, json=create_body(permissions=["*"])).status_code == 403
    response = c.post("/api/v1/tokens", headers=parent_auth, json=create_body())
    assert response.status_code == 201
    child = response.json()
    assert c.get("/api/v1/products", headers=bearer(child["token"])).status_code == 200
    assert len(c.get("/api/v1/tokens", headers=parent_auth).json()["items"]) == 1
    assert c.patch(f"/api/v1/tokens/{parent['record']['id']}", headers=parent_auth,
                   json={"permissions": ["*"]}).status_code == 404
    assert c.delete(f"/api/v1/tokens/{parent['record']['id']}", headers=ADMIN).status_code == 204
    assert c.get("/api/v1/products", headers=bearer(child["token"])).status_code == 401


def test_parent_permission_and_group_changes_restrict_child(client):
    c, _ = client
    expiry = int(time.time()) + 3600
    parent = issue(c, permissions=["token.create", "product.read", "group.read"], groups=[GROUP_A, GROUP_B], expiry=expiry)
    child = issue(c, permissions=["product.read", "group.read"], groups=[GROUP_A], expiry=expiry,
                  actor=bearer(parent["token"]))
    assert c.get("/api/v1/products", headers=bearer(child["token"])).json()["total"] == 1
    response = c.patch(f"/api/v1/tokens/{parent['record']['id']}", headers=ADMIN,
                       json={"permissions": ["token.create", "group.read"], "groupIds": [GROUP_B]})
    assert response.status_code == 200
    assert c.get("/api/v1/products", headers=bearer(child["token"])).status_code == 403
    assert c.get("/api/v1/product-groups", headers=bearer(child["token"])).json()["groups"] == []


def test_expiry_rpa_audience_and_store_outage_fail_closed(client, monkeypatch):
    c, path = client
    expiry = int(time.time()) + 30
    read = issue(c, permissions=["product.read"], expiry=expiry)
    rpa = issue(c, permissions=["rpa.read"], groups=[GROUP_A], expiry=expiry)
    assert c.get("/rpa/v1/product-groups", headers=bearer(read["token"])).status_code == 403
    assert len(c.get("/rpa/v1/product-groups", headers=bearer(rpa["token"])).json()["groups"]) == 1
    assert c.get("/api/v1/products", headers=bearer(rpa["token"])).status_code == 403
    assert c.get("/api/v1/products", headers=RPA).status_code == 401
    assert c.get("/rpa/v1/product-groups", headers=ADMIN).status_code == 401
    with monkeypatch.context() as temporary:
        temporary.setattr("app.core.security.scoped_tokens.time.time", lambda: expiry + 1)
        assert c.get("/api/v1/products", headers=bearer(read["token"])).status_code == 401
    path.rename(path.with_suffix(".away"))
    assert c.get("/api/v1/products", headers=bearer(read["token"])).status_code == 503
    assert c.get("/api/v1/products", headers=ADMIN).status_code == 200


def test_invalid_permissions_are_rejected_and_scope_metadata_is_not_an_authorization_bypass(client):
    c, _ = client
    assert c.post("/api/v1/tokens", headers=ADMIN,
                  json={"name": "bad", "permissions": ["invented.permission"]}).status_code == 422
    assert c.post("/api/v1/tokens", headers=ADMIN,
                  json={"name": "bad", "permissions": ["product.read"], "groupIds": []}).status_code == 422
    token = issue(c, permissions=["product.read"])
    auth = bearer(token["token"])
    caps = c.get("/api/v1/capabilities", headers=auth).json()
    assert caps["permissions"] == ["product.read"] and caps["productEdit"] is False and caps["export"] is False
    for method, path, body in [("post", "/api/v1/product-groups", {"name": "x"}),
                               ("post", "/api/v1/products", {"title": "x"}),
                               ("post", "/api/v1/products/export-uu", {"productIds": [PRODUCT]}),
                               ("post", "/api/v1/prechecks/query", {"productIds": [PRODUCT]}),
                               ("post", "/api/v1/category-lookup/search", {"keyword": "x"}),
                               ("get", "/api/v1/central/status", None),
                               ("get", "/api/v1/tokens", None)]:
        assert c.request(method, path, headers=auth, json=body).status_code == 403


def test_cli_self_service_creates_updates_and_revokes_without_reprinting_secret(client):
    c, _ = client
    def run(*args):
        result = subprocess.run([sys.executable, "-m", "app.modules.access_tokens.cli", *args],
                                capture_output=True, text=True, encoding="utf-8")
        assert result.returncode == 0, result.stderr
        return json.loads(result.stdout)
    created = run("create", "--name", "CLI user", "--permissions", "product.read,group.read",
                  "--group", GROUP_A, "--expires-days", "1")
    secret, token_id = created["token"], created["record"]["id"]
    assert c.get("/api/v1/products", headers=bearer(secret)).status_code == 200
    assert secret not in json.dumps(run("list"))
    changed = run("update", token_id, "--permissions", "group.read")
    assert secret not in json.dumps(changed)
    assert c.get("/api/v1/products", headers=bearer(secret)).status_code == 403
    assert run("revoke", token_id)["revoked"] == token_id
    assert c.get("/api/v1/product-groups", headers=bearer(secret)).status_code == 401
