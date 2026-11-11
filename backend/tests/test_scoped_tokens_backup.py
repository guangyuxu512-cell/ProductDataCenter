import importlib.util
from pathlib import Path

from app.core.security.scoped_tokens import MASTER, TokenStore


def test_registry_online_backup_is_complete_and_contains_no_raw_token(tmp_path):
    spec = importlib.util.spec_from_file_location("token_backup", Path(__file__).resolve().parents[2] / "scripts/backup_scoped_tokens.py")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    registry = TokenStore(tmp_path / "source.sqlite3")
    record, secret = registry.create(MASTER, "backup test", ["product.read"], None, None)
    saved = module.backup_file(registry.path, tmp_path / "backup")
    assert secret.encode() not in saved.read_bytes()
    assert TokenStore(saved).authenticate(secret).token_id == record["id"]
    assert TokenStore(saved).list(MASTER)[0]["name"] == "backup test"
