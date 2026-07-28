from __future__ import annotations

import secrets
from pathlib import Path

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_prefix="SOCCERSNAP_", env_file=".env", extra="ignore")

    data_dir: Path = Path("./data")
    database_url: str = "sqlite:///./data/soccersnap.db"
    host: str = "127.0.0.1"
    port: int = 7420
    secret_key: str = ""
    ops_api_key: str = ""
    demo_team_code: str = "SNAP26"
    admin_user: str = "admin"
    admin_password: str = ""
    software_version: str = "1.0.0"
    min_free_gb: float = 1.0
    simulate_hardware: bool = True
    max_upload_bytes: int = 2_147_483_648  # 2 GiB
    demo_mode: bool = False

    def ensure_demo_secrets(self) -> dict[str, str]:
        """Generate ephemeral demo credentials for any secret left unset."""
        if not self.demo_mode:
            return {}
        generated: dict[str, str] = {}
        if not self.secret_key:
            self.secret_key = secrets.token_urlsafe(32)
            generated["SOCCERSNAP_SECRET_KEY"] = "(generated)"
        if not self.ops_api_key:
            self.ops_api_key = secrets.token_urlsafe(24)
            generated["SOCCERSNAP_OPS_API_KEY"] = self.ops_api_key
        if not self.admin_password:
            self.admin_password = secrets.token_urlsafe(12)
            generated["SOCCERSNAP_ADMIN_PASSWORD"] = self.admin_password
        return generated

    def validate_runtime_secrets(self) -> None:
        """Refuse placeholder/blank secrets outside explicit demo mode."""
        if self.demo_mode:
            return
        placeholders = {
            "",
            "change-me-in-production",
            "change-me-ops-key",
            "soccersnap",
            "soccersnap-dev-secret",
            "soccersnap-ops",
            "admin",
            "password",
        }
        if self.secret_key in placeholders:
            raise RuntimeError("SOCCERSNAP_SECRET_KEY must be set to a unique value")
        if self.ops_api_key in placeholders:
            raise RuntimeError("SOCCERSNAP_OPS_API_KEY must be set to a unique value")
        if self.admin_password in placeholders:
            raise RuntimeError("SOCCERSNAP_ADMIN_PASSWORD must be set to a unique value")

    @property
    def recordings_dir(self) -> Path:
        return self.data_dir / "recordings"

    @property
    def staging_dir(self) -> Path:
        return self.data_dir / "staging"

    @property
    def media_dir(self) -> Path:
        return self.data_dir / "media"

    def ensure_dirs(self) -> None:
        for path in (self.data_dir, self.recordings_dir, self.staging_dir, self.media_dir):
            path.mkdir(parents=True, exist_ok=True)


settings = Settings()
