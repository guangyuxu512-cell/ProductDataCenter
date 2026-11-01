from functools import lru_cache
from pathlib import Path

from pydantic import Field, SecretStr, field_validator, model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_prefix="BACKEND_", env_file=".env", extra="ignore", hide_input_in_errors=True)

    database_url: str | None = Field(default=None, repr=False)
    database_url_file: Path | None = None
    api_token: SecretStr | None = None
    api_token_file: Path | None = None
    rpa_api_token: SecretStr | None = None
    rpa_api_token_file: Path | None = None
    data_root: Path = Path("/data")
    enable_group_writes: bool = False
    export_max_bytes: int = Field(default=128 * 1024 * 1024, ge=1024)
    # Optional service-to-service access. Invalid or missing connection details
    # fail only this integration, not the existing product and RPA services.
    central_application_enabled: bool | None = False
    central_application_base_url: str | None = Field(default=None, repr=False)
    central_application_id: str = "product-library"
    central_application_token_file: Path | None = Field(default=None, repr=False)

    @field_validator("central_application_enabled", mode="before")
    @classmethod
    def parse_optional_central_switch(cls, value):
        if isinstance(value, bool):
            return value
        if isinstance(value, str):
            normalized = value.strip().lower()
            if normalized in {"true", "1", "yes", "on"}:
                return True
            if normalized in {"false", "0", "no", "off", ""}:
                return False
        # Invalid optional integration config must not take existing APIs down.
        return None

    @model_validator(mode="after")
    def check_postgres(self):
        if self.rpa_api_token and self.rpa_api_token_file:
            raise ValueError("RPA 访问凭据只能配置值或凭据文件其中一项")
        if self.database_url_file:
            if self.database_url:
                raise ValueError("数据库连接只能配置 URL 或凭据文件其中一项")
            self.database_url = self.database_url_file.read_text(encoding="utf-8").strip()
            if not self.database_url:
                raise ValueError("数据库连接凭据文件不能为空")
        if self.database_url and not self.database_url.startswith("postgresql+psycopg://"):
            raise ValueError("BACKEND_DATABASE_URL 必须使用 postgresql+psycopg")
        return self

    def configured_token(self) -> str:
        if self.api_token_file:
            return self.api_token_file.read_text(encoding="utf-8").strip()
        return self.api_token.get_secret_value() if self.api_token else ""

    def configured_rpa_token(self) -> str:
        if self.rpa_api_token_file:
            return self.rpa_api_token_file.read_text(encoding="utf-8").strip()
        return self.rpa_api_token.get_secret_value() if self.rpa_api_token else ""


@lru_cache
def get_settings() -> Settings:
    return Settings()
