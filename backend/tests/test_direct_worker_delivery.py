import hashlib
import json
from types import SimpleNamespace
from uuid import uuid4

import httpx
from fastapi.testclient import TestClient

from app.core.config import Settings
from app.main import create_application
from app.modules.central.client import CentralApplicationClient, CentralConnectionError
from app.modules.prechecks import worker_delivery


def test_worker_result_is_direct_and_authenticated_without_product_write_token(monkeypatch):
    task_id, device_id = uuid4(), uuid4()
    token = "ccw_synthetic_device_token"
    body = {"status": "success", "result": {"items": []}, "error_code": None, "error_message": None}
    wire = json.dumps(body, separators=(",", ":")).encode()
    context = SimpleNamespace(task_id=task_id, device_id=device_id)
    calls = []
    settings = Settings(_env_file=None, auto_precheck_enabled=True, worker_precheck_enabled=True)

    class Central:
        def __init__(self, settings):
            pass
        def worker_delivery_context(self, actual_task, actual_device, actual_token):
            calls.append("verify")
            assert (actual_task, actual_device, actual_token) == (task_id, device_id, token)
            return context

    class Runner:
        def __init__(self, engine, settings):
            pass
        def accept_worker_delivery(self, actual_context, terminal, digest):
            calls.append("save")
            assert actual_context is context and terminal.result == {"items": []}
            assert digest == hashlib.sha256(wire).hexdigest()
            return True

    monkeypatch.setattr(worker_delivery, "get_settings", lambda: settings)
    monkeypatch.setattr(worker_delivery, "get_database_engine", lambda: object())
    monkeypatch.setattr(worker_delivery, "CentralApplicationClient", Central)
    monkeypatch.setattr(worker_delivery, "PrecheckRunner", Runner)
    app = create_application()
    with TestClient(app) as client:
        response = client.post(f"/api/v1/worker-precheck-results/{task_id}", content=wire,
                               headers={"Authorization": "Bearer " + token, "X-Device-ID": str(device_id)})
        assert response.status_code == 200
        assert response.json() == {"task_id": str(task_id), "accepted": True}
        assert client.post(f"/api/v1/worker-precheck-results/{task_id}", content=wire).status_code == 401
    assert calls == ["verify", "save"]


def test_central_checks_the_existing_worker_identity_and_task(tmp_path):
    task_id, device_id = uuid4(), uuid4()
    app_token = "synthetic-central-token-0123456789abcdef"
    worker_token = "ccw_synthetic_device_token"
    token_file = tmp_path / "central-token"
    token_file.write_text(app_token, encoding="ascii")
    settings = Settings(_env_file=None, central_application_enabled=True,
                        central_application_base_url="https://central.test", central_application_token_file=token_file)

    def handler(request):
        assert request.headers["authorization"] == "Bearer " + worker_token
        assert request.headers["x-device-id"] == str(device_id)
        assert request.url.path == f"/api/v1/worker/tasks/{task_id}/precheck-delivery-context"
        return httpx.Response(200, headers={"Cache-Control": "no-store"}, json={
            "task_id": str(task_id), "client_id": "product-library", "product_id": "12345678", "revision": 1,
            "device_id": str(device_id), "category_id": "123", "local_shop_id": "local", "platform_shop_id": "shop"})

    client = CentralApplicationClient(settings, transport=httpx.MockTransport(handler))
    assert client.worker_delivery_context(task_id, device_id, worker_token).product_id == "12345678"

    denied = CentralApplicationClient(settings, transport=httpx.MockTransport(lambda request: httpx.Response(403)))
    try:
        denied.worker_delivery_context(task_id, device_id, worker_token)
        assert False, "unapproved Worker must be rejected"
    except CentralConnectionError as error:
        assert error.reason == "worker_denied"
