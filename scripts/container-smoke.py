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
    password, token, web_password, rpa_token, central_token = (secrets.token_urlsafe(32) for _ in range(5))
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
        (credentials / "rpa_token").write_text(rpa_token)
        (credentials / "central_token").write_text(central_token)
        hashed = command("openssl", "passwd", "-6", "-stdin", stdin=web_password + "\n")
        (credentials / "htpasswd").write_text("reviewer:" + hashed + "\n")
        with socket.socket() as sock:
            sock.bind(("127.0.0.1", 0))
            port = sock.getsockname()[1]
        with socket.socket() as sock:
            sock.bind(("127.0.0.1", 0))
            local_api_port = sock.getsockname()[1]
        while local_api_port == port:
            with socket.socket() as sock:
                sock.bind(("127.0.0.1", 0))
                local_api_port = sock.getsockname()[1]
        env = dict(os.environ, RELEASE_SHA=run, DATABASE_URL_FILE=str(credentials / "database_url"),
                   API_TOKEN_FILE=str(credentials / "api_token"), WEB_HTPASSWD_FILE=str(credentials / "htpasswd"),
                   NAS_DATA_ROOT=str(media), NAS_NETWORK=run, WEB_BIND_ADDRESS="127.0.0.1", WEB_PORT=str(port),
                   BACKEND_ENABLE_GROUP_WRITES="false", RPA_TOKEN_FILE=str(credentials / "rpa_token"),
                   PRODUCT_API_IMAGE=f"product-data-center-api:{run}",
                   PRODUCT_WEB_IMAGE=f"product-data-center-web:{run}", LOCAL_API_PORT=str(local_api_port),
                   CENTRAL_APPLICATION_BASE_URL="https://control-center.invalid",
                   CENTRAL_APPLICATION_TOKEN_FILE=str(credentials / "central_token"))
        def compose(*args, **kwargs):
            return command("docker", "compose", "-p", run, "-f", str(ROOT / "deploy/compose.yaml"),
                           "-f", str(ROOT / "deploy/compose.rpa.yaml"), *args, env=env, **kwargs)
        def synology_compose(*args, **kwargs):
            return command("docker", "compose", "-p", run + "-host", "-f",
                           str(ROOT / "deploy/compose.synology-lan.yaml"), *args, env=env, **kwargs)
        def central_compose(*args, **kwargs):
            return command("docker", "compose", "-p", run, "-f", str(ROOT / "deploy/compose.yaml"),
                           "-f", str(ROOT / "deploy/compose.rpa.yaml"), "-f",
                           str(ROOT / "deploy/compose.central.yaml"), *args, env=env, **kwargs)
        def psql(sql):
            return command("docker", "exec", "-i", postgres, "psql", "-X", "-v", "ON_ERROR_STOP=1", "-U", "pdc_test", "-d", "product_workbench_test", stdin=sql)
        base = f"http://127.0.0.1:{port}"
        basic = base64.b64encode(f"reviewer:{web_password}".encode()).decode()
        def request(path, *, status=200, method="GET", body=None, auth=True, bearer=None):
            headers = {"Authorization": "Basic " + basic} if auth else {}
            if bearer is not None:
                headers["Authorization"] = "Bearer " + bearer
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
            # The init-only server accepts Unix sockets before restarting. Wait
            # for TCP, which is only enabled on the final PostgreSQL process.
            wait_for(lambda: "accepting connections" in command("docker", "exec", postgres, "pg_isready", "-h", "127.0.0.1", "-U", "pdc_test", "-d", "product_workbench_test"), "PostgreSQL")
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
            request("/rpa/v1/product-groups", auth=False, status=401)
            request("/rpa/v1/product-groups", auth=False, bearer=token, status=401)
            groups = request("/rpa/v1/product-groups", auth=False, bearer=rpa_token)
            assert any(item["groupId"] == group and item["productCount"] == 1 for item in groups["groups"])
            page = request("/rpa/v1/product-groups/" + group + "/products", auth=False, bearer=rpa_token)
            assert page["items"][0]["product_id"] == IDENTITY
            rpa_uu = request("/rpa/v1/products/" + IDENTITY + "/uu?expected_sha256=" + hashlib.sha256(UU).hexdigest(),
                             auth=False, bearer=rpa_token)
            assert rpa_uu == json.loads(UU)
            request("/rpa/v1/products/" + IDENTITY + "/uu?expected_sha256=" + "0" * 64,
                    auth=False, bearer=rpa_token, status=409)
            request("/api/v1/product-groups", method="POST", body={"name": "RPA不能写"},
                    auth=False, bearer=rpa_token, status=401)
            request("/rpa/v1/product-groups", method="POST", body={"name": "RPA不能写"},
                    auth=False, bearer=rpa_token, status=405)
            print("PASS: RPA proxy, independent read-only token, group/list, UU version and write rejection", flush=True)
            assert request("/api/v1/product-groups/" + group, method="PATCH", body={"name": "改名"})["group"]["productCount"] == 1
            assert request("/api/v1/product-groups/" + group, method="DELETE")["deleted"]["productCount"] == 1
            assert request("/api/v1/products/" + IDENTITY)["product"]["group_id"] is None
            assert request("/api/v1/products")["total"] == 1
            print("PASS: restricted-role group CRUD/move, product preserved", flush=True)

            # Test opt-in anonymous LAN access separately from the default Basic mode.
            # The RPA route remains independently authenticated in both modes.
            env["WEB_ACCESS_MODE"] = "lan"
            env["WEB_TRUSTED_CIDR"] = "192.168.0.0/24"
            compose("up", "-d", "--no-build", "--force-recreate", "--no-deps", "--wait", "--wait-timeout", "100", "product-web")
            request("/", auth=False, status=403)
            request("/api/v1/products", auth=False, status=403)
            assert request("/rpa/v1/product-groups", auth=False, bearer=rpa_token)["groups"] == []
            request("/rpa/v1/product-groups", auth=False, status=401)

            # Published localhost ports reach Nginx from the bridge gateway.
            web_id = compose("ps", "-q", "product-web")
            gateway = command("docker", "inspect", "--format", "{{range .NetworkSettings.Networks}}{{.Gateway}}{{end}}", web_id)
            env["WEB_TRUSTED_CIDR"] = gateway + "/32"
            compose("up", "-d", "--no-build", "--force-recreate", "--no-deps", "--wait", "--wait-timeout", "100", "product-web")
            assert b"<html" in request("/", auth=False)
            assert request("/api/v1/products", auth=False)["total"] == 1
            request("/api/v1/product-groups", method="POST", body={"name": "RPA 不能写"}, auth=False, bearer=rpa_token, status=401)
            request("/rpa/v1/product-groups", auth=False, bearer=rpa_token)
            request("/rpa/v1/product-groups", auth=False, status=401)
            request("/rpa/v1/product-groups", auth=False, bearer="wrong", status=401)
            print("PASS: anonymous trusted network, denied other network, unchanged RPA credentials", flush=True)

            # Adding the optional central connection must retain existing RPA,
            # product and database settings. The endpoint is intentionally
            # unreachable and uses only a synthetic credential.
            central_compose("up", "-d", "--no-build", "--force-recreate", "--no-deps",
                            "--wait", "--wait-timeout", "100", "product-api")
            wait_for(lambda: request("/api/v1/capabilities", auth=False)["groupWrites"], "central overlay product API")
            status = request("/api/v1/central/status", auth=False)
            assert status["state"] == "unavailable" and status["reason"] == "upstream_unavailable"
            assert request("/api/v1/products", auth=False)["total"] == 1
            assert request("/rpa/v1/product-groups", auth=False, bearer=rpa_token)["groups"] == []
            request("/rpa/v1/product-groups", auth=False, status=401)
            print("PASS: central overlay fails safely and preserves product/RPA access", flush=True)

            # The Synology variant preserves source IP on host networking and
            # proxies to a separate API container via host loopback. Use the
            # same isolated database and fixture credentials, never production.
            compose("down", "--remove-orphans")
            env["WEB_TRUSTED_CIDR"] = "192.168.0.0/24"
            synology_compose("up", "-d", "--no-build", "--wait", "--wait-timeout", "100")
            wait_for(lambda: request("/health", auth=False)["status"] == "ok", "Synology host web")
            assert b"<html" in request("/", auth=False)
            assert request("/api/v1/products", auth=False)["total"] == 1
            request("/rpa/v1/product-groups", auth=False, status=401)
            request("/rpa/v1/product-groups", auth=False, bearer="wrong", status=401)
            assert request("/rpa/v1/product-groups", auth=False, bearer=rpa_token)["groups"] == []
            assert request("/rpa/v1/products/" + IDENTITY + "/uu?expected_sha256=" + hashlib.sha256(UU).hexdigest(),
                           auth=False, bearer=rpa_token) == json.loads(UU)
            request("/api/v1/product-groups", method="POST", body={"name": "RPA不能写"},
                    auth=False, bearer=rpa_token, status=401)
            request("/rpa/v1/product-groups", method="POST", body={"name": "RPA不能写"},
                    auth=False, bearer=rpa_token, status=405)
            print("PASS: Synology host proxy, loopback API, RPA token and UU", flush=True)
        finally:
            synology_compose("down", "--remove-orphans", check=False)
            compose("down", "--remove-orphans", check=False)
            command("docker", "rm", "-f", postgres, check=False)
            command("docker", "network", "rm", run, check=False)
            for service in ("api", "web"):
                command("docker", "image", "rm", f"product-data-center-{service}:{run}", check=False)


if __name__ == "__main__":
    main()
