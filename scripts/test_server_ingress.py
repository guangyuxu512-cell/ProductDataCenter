"""Exercise the candidate TLS ingress with synthetic loopback-only services."""
import base64
import hashlib
import http.client
import os
from pathlib import Path
import shutil
import socket
import ssl
import subprocess
import tempfile
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer


class Handler(BaseHTTPRequestHandler):
    def log_message(self, *_args):
        pass

    def do_GET(self):
        authorization = self.headers.get("Authorization", "")
        if self.server.kind == "api":
            code = 200 if authorization == "Bearer synthetic-admin" else 401
        elif self.path.startswith("/rpa/v1/") and not self.path.startswith("/rpa/v1/product-images/"):
            code = 200 if authorization == "Bearer synthetic-rpa" else 401
        else:
            code = 200
        body = (self.server.kind + ":" + self.path).encode()
        self.send_response(code)
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def do_POST(self):
        if (self.server.kind != "api" or self.path != "/api/v1/product-images"
                or self.headers.get("Authorization") != "Bearer synthetic-admin"):
            self.send_response(401)
            self.send_header("Content-Length", "0")
            self.end_headers()
            return
        data = self.rfile.read(int(self.headers["Content-Length"]))
        body = hashlib.sha256(data).hexdigest().encode()
        self.send_response(201)
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)


def main():
    nginx = shutil.which("nginx")
    openssl = shutil.which("openssl")
    if not nginx or not openssl:
        raise SystemExit("nginx and openssl are required for this isolated test")
    web = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
    api = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
    web.kind, api.kind = "web", "api"
    for server in (web, api):
        threading.Thread(target=server.serve_forever, daemon=True).start()
    with tempfile.TemporaryDirectory(prefix="pdc-ingress-test-") as directory:
        root = Path(directory)
        root.chmod(0o755)
        (root / "logs").mkdir()
        # A different nginx instance may own the compiled default directory.
        # A large request must use the PDC-specific writable directory instead.
        default_body = root / "client_body_temp"
        default_body.mkdir(mode=0o500)
        temp_root = root / "pdc-temp"
        temp_root.mkdir(mode=0o755)
        for name in ("nginx-client-body", "nginx-proxy", "nginx-fastcgi", "nginx-uwsgi", "nginx-scgi"):
            (temp_root / name).mkdir(mode=0o700)
        cert, key, users = root / "cert.pem", root / "key.pem", root / "users"
        subprocess.run([openssl, "req", "-x509", "-newkey", "rsa:2048", "-nodes", "-days", "1",
                        "-subj", "/CN=127.0.0.1", "-addext", "subjectAltName=IP:127.0.0.1",
                        "-keyout", str(key), "-out", str(cert)], check=True,
                       stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        hashed = subprocess.check_output([openssl, "passwd", "-apr1", "synthetic-basic"], text=True).strip()
        users.write_text("probe:" + hashed + "\n", encoding="utf-8")
        users.chmod(0o644)
        with socket.socket() as sock:
            sock.bind(("127.0.0.1", 0))
            port = sock.getsockname()[1]
        template = (Path(__file__).resolve().parents[1] / "deploy/nginx.server-ingress.conf.template").read_text(encoding="utf-8")
        template = template.replace("/var/lib/product-data-center", str(temp_root))
        values = {"PDC_BIND_IP": "127.0.0.1", "PDC_PUBLIC_PORT": str(port),
                  "PDC_WEB_PORT": str(web.server_port), "PDC_API_PORT": str(api.server_port),
                  "PDC_TLS_CERTIFICATE": str(cert), "PDC_TLS_PRIVATE_KEY": str(key),
                  "PDC_BASIC_AUTH_FILE": str(users)}
        for name, value in values.items():
            template = template.replace("${" + name + "}", value)
        assert "${PDC_" not in template
        conf = root / "nginx.conf"
        version = subprocess.run([nginx, "-V"], capture_output=True, text=True, check=True).stderr
        lua_core = Path("/www/server/nginx/lib/lua/resty/core.lua")
        lua_path = 'lua_package_path "/www/server/nginx/lib/lua/?.lua;;";\n' if lua_core.exists() and "lua_nginx_module" in version else ""
        conf.write_text(f"pid {root / 'nginx.pid'};\nerror_log {root / 'error.log'} warn;\n"
                        "events { worker_connections 128; }\nhttp { access_log off;\n" + lua_path + template + "\n}\n",
                        encoding="utf-8")
        subprocess.run([nginx, "-t", "-c", str(conf), "-p", str(root)], check=True,
                       stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        process = subprocess.Popen([nginx, "-c", str(conf), "-p", str(root), "-g", "daemon off;"],
                                   stdout=subprocess.DEVNULL, stderr=subprocess.PIPE, text=True)
        context = ssl.create_default_context(cafile=str(cert))
        def request(path, authorization=None, *, method="GET", body=None):
            headers = {} if authorization is None else {"Authorization": authorization}
            connection = http.client.HTTPSConnection("127.0.0.1", port, context=context, timeout=5)
            try:
                connection.request(method, path, body=body, headers=headers)
                response = connection.getresponse()
                return response.status, response.read().decode()
            finally:
                connection.close()
        try:
            import time
            for _ in range(50):
                try:
                    request("/")
                    break
                except (OSError, ssl.SSLError):
                    if process.poll() is not None:
                        log = root / "error.log"
                        detail = (process.stderr.read() or "") + (log.read_text(encoding="utf-8") if log.exists() else "")
                        raise RuntimeError("isolated nginx exited: " + detail[-1000:])
                    time.sleep(0.1)
            basic = "Basic " + base64.b64encode(b"probe:synthetic-basic").decode()
            wrong = "Basic " + base64.b64encode(b"probe:wrong").decode()
            assert request("/")[0] == 401
            assert request("/", wrong)[0] == 401
            assert request("/", basic) == (200, "web:/")
            assert request("/api/v1/products?limit=1")[0] == 401
            assert request("/api/v1/products?limit=1", basic) == (200, "web:/api/v1/products?limit=1")
            assert request("/api/v1/products", "Bearer wrong")[0] == 401
            assert request("/api/v1/products?limit=1", "Bearer synthetic-admin") == (200, "api:/api/v1/products?limit=1")
            image_body = bytes(range(256)) * 512
            assert request("/api/v1/product-images", "Bearer synthetic-admin", method="POST", body=image_body) == (
                201, hashlib.sha256(image_body).hexdigest())
            assert (default_body.stat().st_mode & 0o777) == 0o500
            assert request("/rpa/v1/products/example/uu")[0] == 401
            assert request("/rpa/v1/products/example/uu", "Bearer synthetic-rpa")[0] == 200
            assert request("/rpa/v1/product-images/example.png")[0] == 200
            print("isolated_tls_ingress_auth_routing_and_large_upload=passed")
        finally:
            process.terminate()
            try:
                process.wait(timeout=5)
            except subprocess.TimeoutExpired:
                process.kill()
                process.wait()
            web.shutdown()
            api.shutdown()
            web.server_close()
            api.server_close()


if __name__ == "__main__":
    main()
