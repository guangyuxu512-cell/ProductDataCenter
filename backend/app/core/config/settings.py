from functools import lru_cache
from pathlib import Path

from pydantic import Field, SecretStr, model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_prefix="BACKEND_", env_file=".env", extra="ignore")

    database_url: str | None = None
    api_token: SecretStr | None = None
    api_token_file: Path | None = None
    data_root: Path = Path("/data")
    enable_group_writes: bool = False
    export_max_bytes: int = Field(default=128 * 1024 * 1024, ge=1024)

    @model_validator(mode="after")
    def check_postgres(self):
        if self.database_url and not self.database_url.startswith("postgresql+psycopg://"):
            raise ValueError("BACKEND_DATABASE_URL 必须使用 postgresql+psycopg")
        return self

    def configured_token(self) -> str:
        if self.api_token_file:
            return self.api_token_file.read_text(encoding="utf-8").strip()
        return self.api_token.get_secret_value() if self.api_token else ""


@lru_cache
def get_settings() -> Settings:
    return Settings()
