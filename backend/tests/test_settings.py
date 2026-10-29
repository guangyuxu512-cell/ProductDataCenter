import pytest
from pydantic import ValidationError

from app.core.config import Settings


@pytest.fixture(autouse=True)
def isolated_settings_environment(monkeypatch):
    monkeypatch.delenv("BACKEND_DATABASE_URL", raising=False)
    monkeypatch.delenv("BACKEND_DATABASE_URL_FILE", raising=False)


def test_database_connection_file_preserves_url_and_hides_password(tmp_path):
    value = "postgresql+psycopg://reader:private%2Bpassword@postgres:5432/catalogue"
    path = tmp_path / "database_url"
    path.write_text(value + "\n")
    settings = Settings(_env_file=None, database_url_file=path)
    assert settings.database_url == value
    assert "private" not in repr(settings)


def test_database_connection_sources_cannot_be_ambiguous(tmp_path):
    path = tmp_path / "database_url"
    path.write_text("postgresql+psycopg://reader:private-password@postgres/catalogue")
    with pytest.raises(ValidationError) as result:
        Settings(_env_file=None, database_url="postgresql+psycopg://other:another-private@postgres/catalogue", database_url_file=path)
    assert "其中一项" in str(result.value)
    assert "another-private" not in str(result.value)


def test_empty_or_invalid_connection_file_fails_without_echoing_secret(tmp_path):
    path = tmp_path / "database_url"
    path.write_text(" \n")
    with pytest.raises(ValidationError, match="不能为空"):
        Settings(_env_file=None, database_url_file=path)
    path.write_text("bad-driver://reader:do-not-log-this@postgres/catalogue")
    with pytest.raises(ValidationError) as result:
        Settings(_env_file=None, database_url_file=path)
    assert "do-not-log-this" not in str(result.value)


def test_missing_connection_file_does_not_fall_back_to_a_database(tmp_path):
    with pytest.raises(FileNotFoundError):
        Settings(_env_file=None, database_url_file=tmp_path / "missing")
