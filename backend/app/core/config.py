from functools import lru_cache
from pathlib import Path
from urllib.parse import urlparse

from pydantic import Field, model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict
from sqlalchemy import URL

ROOT = Path(__file__).resolve().parents[3]


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=ROOT / ".env", extra="ignore")

    app_env: str = "development"
    app_public_url: str = "http://localhost:5173"
    app_timezone: str = "Asia/Shanghai"
    database_host: str = "127.0.0.1"
    database_port: int = 5433
    database_name: str = "shoppulse"
    database_user: str = "shoppulse"
    database_password_file: str = "secrets/database_password"
    credential_master_key_file: str = "secrets/credential_master_key"
    credential_key_version: int = Field(default=1, ge=1)
    credential_old_keys: dict[int, str] = Field(default_factory=dict)
    # Exact origins authorized by the deployer, e.g. ["http://127.0.0.1:8099"].
    model_allowed_origins: list[str] = Field(default_factory=list)
    storage_root: str = "data"
    job_lease_seconds: int = Field(default=90, ge=10)
    job_heartbeat_seconds: int = Field(default=15, ge=1)
    job_poll_seconds: float = Field(default=2, ge=0.1)
    job_max_attempts: int = Field(default=3, ge=1, le=10)
    log_level: str = "INFO"
    max_upload_mib: int = Field(default=20, ge=1, le=100)
    max_import_rows: int = Field(default=100000, ge=1, le=100000)
    parse_timeout_seconds: int = Field(default=120, ge=5, le=300)

    @model_validator(mode="after")
    def validate_public_url(self):
        parsed = urlparse(self.app_public_url)
        if (
            parsed.scheme not in {"http", "https"}
            or not parsed.hostname
            or parsed.username
            or parsed.password
            or parsed.query
            or parsed.fragment
            or parsed.path not in {"", "/"}
        ):
            raise ValueError("APP_PUBLIC_URL must be an HTTP(S) origin")
        if self.app_env == "production" and parsed.scheme != "https":
            if parsed.hostname not in {"localhost", "127.0.0.1", "::1"}:
                raise ValueError("Production public URLs require HTTPS (except localhost)")
        if self.job_heartbeat_seconds * 2 >= self.job_lease_seconds:
            raise ValueError("Heartbeat must be less than half the lease duration")
        return self

    @property
    def origin(self) -> str:
        return self.app_public_url.rstrip("/")

    def path(self, name: str) -> Path:
        value = Path(name)
        return value if value.is_absolute() else ROOT / value

    def secret(self, filename: str) -> str:
        # Never put file contents or validation input into an exception/log.
        try:
            value = self.path(filename).read_text(encoding="utf-8").strip()
        except OSError:
            raise RuntimeError("Required secret file is unavailable; run init_secrets.py") from None
        if len(value) < 32:
            raise RuntimeError(
                "Secret is too short; use a generated secret of at least 32 characters"
            )
        return value

    def validate_secrets(self) -> None:
        for filename in (
            self.database_password_file,
            self.credential_master_key_file,
        ):
            self.secret(filename)

    @property
    def database_url(self) -> URL:
        return URL.create(
            "postgresql+psycopg",
            username=self.database_user,
            password=self.secret(self.database_password_file),
            host=self.database_host,
            port=self.database_port,
            database=self.database_name,
        )


@lru_cache
def settings() -> Settings:
    return Settings()
