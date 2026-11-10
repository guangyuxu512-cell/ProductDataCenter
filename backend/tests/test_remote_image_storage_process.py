"""Exercise the image-only NAS and cloud API as separate real HTTP processes."""

import base64
import os
import socket
import subprocess
import sys
import time
from pathlib import Path
from urllib.parse import urlsplit

import httpx


PNG = base64.b64decode("iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAQAAAC1HAwCAAAAC0lEQVR42mP8/x8AAwMCAO+/CZYAAAAASUVORK5CYII=")
ADMIN = "isolated-process-admin-token"
STORAGE = "isolated-process-storage-token"
BACKEND = Path(__file__).resolve().parents[1]


def free_port():
    with socket.socket() as sock:
        sock.bind(("127.0.0.1", 0))
        return sock.getsockname()[1]


def start_server(module, port, settings):
    environment = {key: value for key, value in os.environ.items() if not key.startswith("BACKEND_")}
    environment.update(settings)
    process = subprocess.Popen(
        [sys.executable, "-m", "uvicorn", module, "--host", "127.0.0.1", "--port", str(port)],
        cwd=BACKEND, env=environment, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
        creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
    )
    try:
        deadline = time.monotonic() + 15
        while time.monotonic() < deadline and process.poll() is None:
            try:
                if httpx.get(f"http://127.0.0.1:{port}/health", timeout=0.5, trust_env=False).status_code == 200:
                    return process
            except httpx.HTTPError:
                time.sleep(0.1)
        raise AssertionError("isolated HTTP service did not start")
    except Exception:
        stop(process)
        raise


def stop(process):
    if process and process.poll() is None:
        process.terminate()
        try:
            process.wait(timeout=5)
        except subprocess.TimeoutExpired:
            process.kill()
            process.wait(timeout=5)


def test_cloud_upload_writes_only_to_nas_service_and_reports_outage(tmp_path):
    storage_port, cloud_port = free_port(), free_port()
    while cloud_port == storage_port:
        cloud_port = free_port()
    storage_dir = tmp_path / "nas-images"
    storage_dir.mkdir()
    storage_secret = tmp_path / "nas-token"
    storage_secret.write_text(STORAGE, encoding="utf-8")
    common = {"BACKEND_ENABLE_PRODUCT_WRITES": "true", "BACKEND_IMAGE_PUBLIC_BASE_URL": "https://images.example.test"}
    nas = cloud = None
    try:
        nas = start_server("app.image_storage:app", storage_port, {
            **common, "BACKEND_API_TOKEN": STORAGE, "BACKEND_IMAGE_STORAGE_DIR": str(storage_dir),
        })
        cloud = start_server("app.main:app", cloud_port, {
            **common, "BACKEND_API_TOKEN": ADMIN,
            "BACKEND_IMAGE_REMOTE_UPLOAD_ORIGIN": f"http://127.0.0.1:{storage_port}",
            "BACKEND_IMAGE_REMOTE_UPLOAD_TOKEN_FILE": str(storage_secret),
        })
        headers = {"Authorization": "Bearer " + ADMIN, "Content-Type": "image/png"}
        with httpx.Client(timeout=10, trust_env=False) as client:
            upload = client.post(f"http://127.0.0.1:{cloud_port}/api/v1/product-images", headers=headers, content=PNG)
            assert upload.status_code == 201
            path = urlsplit(upload.json()["url"]).path
            name = path.rsplit("/", 1)[1]
            assert (storage_dir / name).read_bytes() == PNG
            assert client.get(f"http://127.0.0.1:{storage_port}" + path).content == PNG
            assert client.get(f"http://127.0.0.1:{storage_port}/api/v1/products").status_code == 404
            stop(nas)
            nas = None
            assert client.post(f"http://127.0.0.1:{cloud_port}/api/v1/product-images", headers=headers, content=PNG).status_code == 503
            assert len(list(storage_dir.iterdir())) == 1
    finally:
        stop(cloud)
        stop(nas)
