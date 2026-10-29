"""Exercise the production Compose against disposable PostgreSQL 16, never NAS.

Requires prebuilt product-api:test and product-web:test images and Docker Compose.
Only containers/networks bearing this invocation's random prefix are removed.
"""
import base64
import hashlib
import io
import json
import os
from pathlib import Path
import secrets
import socket
import subprocess
import tempfile
import time
import urllib.error
import urllib.request
from zipfile import ZipFile

ROOT = Path(__file__).resolve().parents[1]
IDENTITY = "3760269504500859111"
UU = '{\r\n  "goodsInfo": {"productId":"3760269504500859111", "title":"容器验证"}\r\n}\r\n'.encode()


def command(*args, stdin=None, check=True, env=None):
    result = subprocess.run(args, input=stdin, text=True, capture_output=True, env=env)
    if check and result.returncode:
        # Commands can contain credentials; never echo arguments or environment.
        raise RuntimeError(f"{args[0]} failed ({result.returncode}): {result.stderr[-4000:]}")
    return result.stdout.strip()


def wait_for(check, label):
    deadline = time.monotonic() + 90
    while time.monotonic() < deadline:
        try:
            if check():
                return
        except (OSError, RuntimeError):
            pass
        time.sleep(1)
    raise RuntimeError(f"Timed out: {label}")


def main():
    run = "pdc-smoke-" + secrets.token_hex(6)
    postgres = run + "-postgres"
    password, token, web_password = (secrets.token_urlsafe(32) for _ in range(3))
    with tempfile.TemporaryDirectory(prefix=run) as directory:
        root = Path(directory)
        root.chmod(0o755)
        media = root / "data"
        media.mkdir(mode=0o755)
        (media / "fixture-uu.txt").write_bytes(UU)
        (media / "fixture-uu.txt").chmod(0o444)
        credentials = root / "credentials"
        credentials.mkdir(mode=0o755)
        (credentials / "database_url").write_text(f"postgresql+psycopg://pdc_reader:{password}@postgres:5432/product_workbench_test")
        (credentials / "api_token").write_text(token)
        hashed = command("openssl", "passwd", "-6", "-stdin", stdin=web_password + "\n")
        (credentials / "htpasswd").write_text("reviewer:" + hashed + "\n")
        with socket.socket() as sock:
            sock.bind(("127.0.0.1", 0))
            port = sock.getsockname()[1]
        env = dict(os.environ, RELEASE_SHA=run, DATABASE_URL_FILE=str(credentials / "database_url"),
                   API_TOKEN_FILE=str(credentials / "api_token"), WEB_HTPASSWD_FILE=str(credentials / "htpasswd"),
                   NAS_DATA_ROOT=str(media), NAS_NETWORK=run, WEB_BIND_ADDRESS="127.0.0.1", WEB_PORT=str(port),
                   BACKEND_ENABLE_GROUP_WRITES="false")
        def compose(*args, **kwargs):
            return command("docker", "compose", "-p", run, "-f", str(ROOT / "deploy/compose.yaml"), *args, env=env, **kwargs)
        def psql(sql):
            return command("docker", "exec", "-i", postgres, "psql", "-X", "-v", "ON_ERROR_STOP=1", "-U", "pdc_test", "-d", "product_workbench_test", stdin=sql)
        base = f"http://127.0.0.1:{port}"
        basic = base64.b64encode(f"reviewer:{web_password}".encode()).decode()
        def request(path, *, status=200, method="GET", body=None, auth=True):
            headers = {"Authorization": "Basic " + basic} if auth else {}
            if body is not None:
                headers["Content-Type"] = "application/json"
            req = urllib.request.Request(base + path, headers=headers, method=method,
                                         data=json.dumps(body).encode() if body is not None else None)
            try:
                response = urllib.request.urlopen(req, timeout=15)
            except urllib.error.HTTPError as error:
                response = error
            assert response.status == status, f"{method} {path}: {response.status}, expected {status}"
            content = response.read()
            return json.loads(content) if "application/json" in response.headers.get("Content-Type", "") else content
        try:
            command("docker", "network", "create", run)
            command("docker", "run", "--rm", "-v", f"{credentials}:/credentials", "--user", "0", "product-api:test",
                    "python", "-c", "import os,pathlib; [(os.chown(p,1026,100),os.chmod(p,0o440 if p.name!='htpasswd' else 0o444)) for p in pathlib.Path('/credentials').iterdir()]")
            command("docker", "run", "-d", "--name", postgres, "--network", run, "--network-alias", "postgres",
                    "-e", "POSTGRES_USER=pdc_test", "-e", "POSTGRES_DB=product_workbench_test",
                    "-e", f"POSTGRES_PASSWORD={password}", "postgres:16-alpine")
            wait_for(lambda: "accepting connections" in command("docker", "exec", postgres, "pg_isready", "-U", "pdc_test", "-d", "product_workbench_test"), "PostgreSQL")
            for path in sorted((ROOT / "backend/tests/fixtures/collector").glob("*.sql")):
                psql(path.read_text())
            psql(f"""INSERT INTO products(product_id,title,source_platform,source_product_id,captured_at,uu_json,uu_rel_path,uu_sha256)
                VALUES ('{IDENTITY}','容器验证','douyin','{IDENTITY}','2026-10-26T08:18:34.999999+08',
                '{{"goodsInfo":{{"productId":"{IDENTITY}"}}}}','fixture-uu.txt','{hashlib.sha256(UU).hexdigest()}');
                INSERT INTO product_skus(product_id,sku_id,sku_name,sort_order) VALUES ('{IDENTITY}','sku-1','白色',0);
                INSERT INTO product_images(product_id,image_type,sort_order,rel_path,source_url)
                VALUES ('{IDENTITY}','main',0,'','https://fixture.invalid/main.png');
                CREATE ROLE pdc_reader LOGIN PASSWORD '{password}';
                GRANT CONNECT ON DATABASE product_workbench_test TO pdc_reader;
                GRANT USAGE ON SCHEMA public TO pdc_reader;
                GRANT SELECT ON products,product_skus,product_images,product_groups TO pdc_reader;""")
            for service in ("api", "web"):
                command("docker", "tag", f"product-{service}:test", f"product-data-center-{service}:{run}")
            compose("up", "-d", "--no-build", "--wait", "--wait-timeout", "100")
            wait_for(lambda: request("/health", auth=False)["status"] == "ok", "Web")
            request("/", auth=False, status=401)
            request("/api/v1/products", auth=False, status=401)
            assert b"<html" in request("/")
            assert request("/api/v1/capabilities")["groupWrites"] is False
            request("/api/v1/product-groups", method="POST", body={"name": "必须拒绝"}, status=403)
            found = request("/api/v1/products?productId=" + IDENTITY)
            assert found["total"] == 1 and found["items"][0]["product_id"] == IDENTITY
            assert "uu_json" not in found["items"][0]
            assert request("/api/v1/products?includeTotal=false")["total"] is None
            detail = request("/api/v1/products/" + IDENTITY)
            assert len(detail["skus"]) == 1 and len(detail["images"]) == 1
            archive = request("/api/v1/products/export-uu", method="POST", body={"productIds": [IDENTITY]})
            with ZipFile(io.BytesIO(archive)) as zipped:
                manifest = json.loads(zipped.read("manifest.json"))
                record = manifest["products"][0]
                assert record["source"] == "version_file" and zipped.read(record["filename"]) == UU
            api_id = compose("ps", "-q", "product-api")
            command("docker", "exec", api_id, "python", "-c", "import os,httpx; assert os.getuid()==1026; assert httpx.get('http://127.0.0.1:8180/api/v1/products').status_code==401; assert httpx.get('http://127.0.0.1:8180/api/v1/products',headers={'Authorization':'Bearer wrong'}).status_code==401")
            print("PASS: production Compose, UID 1026, secret files, Basic/Bearer auth, list/detail, original UU bytes", flush=True)
            psql("GRANT INSERT,UPDATE,DELETE ON product_groups TO pdc_reader; GRANT UPDATE(group_id) ON products TO pdc_reader;")
            env["BACKEND_ENABLE_GROUP_WRITES"] = "true"
            compose("up", "-d", "--no-build", "--force-recreate", "--wait", "--wait-timeout", "100")
            wait_for(lambda: request("/api/v1/capabilities")["groupWrites"], "group writes")
            group = request("/api/v1/product-groups", method="POST", body={"name": "隔离分组"})["group"]["groupId"]
            assert request("/api/v1/products/group", method="PATCH", body={"productIds": [IDENTITY], "groupId": group})["updated"] == [IDENTITY]
            assert request("/api/v1/product-groups/" + group, method="PATCH", body={"name": "改名"})["group"]["productCount"] == 1
            assert request("/api/v1/product-groups/" + group, method="DELETE")["deleted"]["productCount"] == 1
            assert request("/api/v1/products/" + IDENTITY)["product"]["group_id"] is None
            assert request("/api/v1/products")["total"] == 1
            print("PASS: restricted-role group CRUD/move, product preserved", flush=True)
        finally:
            compose("down", "--remove-orphans", check=False)
            command("docker", "rm", "-f", postgres, check=False)
            command("docker", "network", "rm", run, check=False)
            for service in ("api", "web"):
                command("docker", "image", "rm", f"product-data-center-{service}:{run}", check=False)


if __name__ == "__main__":
    main()
