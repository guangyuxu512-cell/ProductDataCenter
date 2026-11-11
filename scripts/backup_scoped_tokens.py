"""Take a consistent SQLite backup; never print or accept a Token value."""
import argparse
from contextlib import closing
import os
from pathlib import Path
import sqlite3
import stat
import tempfile
from datetime import datetime, timezone
from urllib.parse import quote
from uuid import uuid4


def backup_file(source: Path, destination: Path) -> Path:
    source = Path(source)
    destination = Path(destination)
    if source.is_symlink() or not source.is_file() or not stat.S_ISREG(source.stat().st_mode):
        raise RuntimeError("Token registry is missing or is not a regular file")
    if destination.is_symlink():
        raise RuntimeError("Backup directory must not be a symlink")
    destination.mkdir(mode=0o700, parents=True, exist_ok=True)
    os.chmod(destination, 0o700)
    name = "scoped-tokens-" + datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ") + "-" + uuid4().hex[:8] + ".sqlite3"
    fd, temp_name = tempfile.mkstemp(prefix=".token-backup-", suffix=".sqlite3", dir=str(destination))
    os.close(fd)
    temporary = Path(temp_name)
    try:
        source_uri = "file:" + quote(str(source.resolve()), safe="/:") + "?mode=ro"
        with closing(sqlite3.connect(source_uri, uri=True, timeout=10)) as origin, \
                closing(sqlite3.connect(temporary, timeout=10)) as copy:
            origin.backup(copy)
            if copy.execute("PRAGMA integrity_check").fetchone()[0] != "ok":
                raise RuntimeError("Token backup failed integrity check")
            copy.commit()
        os.chmod(temporary, 0o600)
        with temporary.open("rb+") as f:
            os.fsync(f.fileno())
        result = destination / name
        os.replace(temporary, result)
        return result
    finally:
        if temporary.exists():
            temporary.unlink()


def main():
    parser = argparse.ArgumentParser(description="备份商品库 Token 元数据")
    parser.add_argument("--source", type=Path, required=True)
    parser.add_argument("--destination", type=Path, required=True)
    args = parser.parse_args()
    result = backup_file(args.source, args.destination)
    print("token_registry_backup=" + result.name)


if __name__ == "__main__":
    main()
