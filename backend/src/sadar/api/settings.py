"""Typed runtime configuration with no repository-relative defaults."""

from __future__ import annotations

from pathlib import Path

from pydantic import AliasChoices, Field, PositiveInt
from pydantic_settings import BaseSettings, SettingsConfigDict

from sadar.api.evaluation import MAX_INPUT_BYTES


class Settings(BaseSettings):
    """Production settings. Tests construct this object explicitly."""

    model_config = SettingsConfigDict(extra="ignore", populate_by_name=True)

    release_dir: Path = Field(
        validation_alias=AliasChoices(
            "SADAR_APPROACH_RELEASE_DIR",
            "SADAR_RELEASE_DIR",
        )
    )
    frontend_dir: Path | None = Field(default=None, alias="SADAR_FRONTEND_DIR")
    evaluation_enabled: bool = Field(default=False, alias="SADAR_ENABLE_EVALUATION")
    evaluation_rate_window_s: PositiveInt = Field(
        default=60,
        alias="SADAR_EVALUATION_RATE_WINDOW_S",
    )
    evaluation_global_limit: PositiveInt = Field(
        default=10,
        alias="SADAR_EVALUATION_GLOBAL_LIMIT",
    )
    evaluation_client_limit: PositiveInt = Field(
        default=5,
        alias="SADAR_EVALUATION_CLIENT_LIMIT",
    )
    upload_idle_seconds: float = Field(default=5.0, gt=0)
    upload_total_seconds: float = Field(default=60.0, gt=0)

    @property
    def maximum_multipart_bytes(self) -> int:
        return MAX_INPUT_BYTES + 64 * 1024

    def validated_frontend_dir(self) -> Path | None:
        if self.frontend_dir is None:
            return None
        root = self.frontend_dir.resolve(strict=True)
        if not root.is_dir() or not (root / "index.html").is_file():
            raise ValueError("SADAR_FRONTEND_DIR must contain index.html")
        return root
