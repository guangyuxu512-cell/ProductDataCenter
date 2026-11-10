"""Validate the server candidate with synthetic values and no real database."""
import json
import os
from pathlib import Path
import subprocess
import tempfile


def main():
    root = Path(__file__).resolve().parents[1]
    with tempfile.TemporaryDirectory(prefix="pdc-compose-test-") as directory:
        temp = Path(directory)
        fake = temp / "entrypoint"
        fake.write_text("#!/bin/sh\nprintf '%s\\n' \"$@\"\n", encoding="utf-8")
        fake.chmod(0o755)
        env = os.environ.copy()
        env.update({
            "PDC_PG_BOOTSTRAP_USER": "pdc_test", "PDC_PG_BOOTSTRAP_PASSWORD_FILE": str(fake),
            "PDC_PG_DATA_DIR": str(temp), "PDC_SERVER_TAILNET_IP": "100.64.1.2", "PDC_PG_PORT": "25491",
            "PDC_API_IMAGE": "pdc-api-test:isolated", "PDC_WEB_IMAGE": "pdc-web-test:isolated",
            "PDC_API_PORT": "25492", "PDC_WEB_PORT": "25493", "PDC_DATABASE_URL_FILE": str(fake),
            "PDC_API_TOKEN_FILE": str(fake), "PDC_RPA_TOKEN_FILE": str(fake),
            "PRODUCT_IMAGE_STORAGE_TOKEN_FILE": str(fake), "PDC_WEB_HTPASSWD_FILE": str(fake),
            "PDC_NAS_DATA_MOUNT": str(temp), "PDC_CATEGORY_CACHE_DIR": str(temp),
            "PRODUCT_IMAGE_PUBLIC_BASE_URL": "https://images.example.test",
            "PRODUCT_IMAGE_REMOTE_UPLOAD_ORIGIN": "http://100.64.1.3:25489",
        })
        result = subprocess.run(["docker", "compose", "-f", str(root / "deploy/compose.server-preparation.yaml"),
                                 "config", "--format", "json"], env=env, check=True,
                                capture_output=True, text=True)
        services = json.loads(result.stdout)["services"]
        db, api, web = (services[name] for name in ("product-postgres", "product-api", "product-web"))
        assert db["network_mode"] == api["network_mode"] == web["network_mode"] == "host"
        assert not db.get("ports") and not api.get("ports") and not web.get("ports")
        assert db["environment"]["POSTGRES_HOST_AUTH_METHOD"] == "scram-sha-256"
        assert db["environment"]["POSTGRES_INITDB_ARGS"] == "--auth-host=scram-sha-256 --auth-local=scram-sha-256"
        assert api["command"][-4:] == ["--host", "127.0.0.1", "--port", "25492"]
        assert "listen 127.0.0.1:" in web["command"][0]
        data_mount = next(item for item in api["volumes"] if item["target"] == "/data")
        assert data_mount["read_only"] and not data_mount.get("bind", {}).get("create_host_path", False)
        assert api["read_only"] and api["environment"]["BACKEND_ENABLE_PRODUCT_WRITES"] == "false"
        # `compose config` escapes dollar signs so its output can be reused as
        # Compose input; a container receives their single-dollar form.
        command = db["command"][0].replace("$$", "$")
        def validate(address, port="25491"):
            return subprocess.run(["docker", "run", "--rm", "--network", "none", "--entrypoint", "/bin/sh",
                                   "-e", "PDC_SERVER_TAILNET_IP=" + address, "-e", "PDC_PG_PORT=" + port,
                                   "-v", str(fake) + ":/usr/local/bin/docker-entrypoint.sh:ro",
                                   "postgres:16-alpine", "-ec", command], capture_output=True, text=True)
        good = validate("100.64.1.2")
        assert good.returncode == 0, good.stderr
        assert "listen_addresses=127.0.0.1,100.64.1.2" in good.stdout
        for address in ("0.0.0.0", "192.168.1.1", "100.63.1.2", "100.128.1.2", "100.64.1.256", "100..1.2"):
            assert validate(address).returncode != 0, address
        for port in ("0", "65536", "5432;bad"):
            assert validate("100.64.1.2", port).returncode != 0, port
        print("server_compose_private_bind_and_loopback=passed")


if __name__ == "__main__":
    main()
