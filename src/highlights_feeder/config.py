from datetime import time
from functools import lru_cache
from pathlib import Path

from pydantic import Field, SecretStr
from pydantic_settings import (
    BaseSettings,
    PydanticBaseSettingsSource,
    SettingsConfigDict,
    TomlConfigSettingsSource,
)


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        env_ignore_empty=True,
        toml_file="feeder.toml",
        extra="ignore",
    )

    @classmethod
    def settings_customise_sources(
        cls,
        settings_cls: type[BaseSettings],
        init_settings: PydanticBaseSettingsSource,
        env_settings: PydanticBaseSettingsSource,
        dotenv_settings: PydanticBaseSettingsSource,
        file_secret_settings: PydanticBaseSettingsSource,
    ) -> tuple[PydanticBaseSettingsSource, ...]:
        return (
            init_settings,
            env_settings,
            dotenv_settings,
            TomlConfigSettingsSource(settings_cls),
            file_secret_settings,
        )

    # Notion
    notion_token: SecretStr
    highlights_database_id: str
    library_database_id: str

    # Property names in the "Highlights" database (case-sensitive, must match Notion exactly)
    prop_highlight_name: str = "Name"
    prop_highlight_keywords: str = "Keywords"
    prop_highlight_favorite: str = "Favorite"
    prop_highlight_page: str = "Page"
    prop_highlight_source: str = "Source"
    # Property names in the "Library" database
    prop_book_name: str = "Name"

    # Storage: local SQLite cache + encrypted review history (committed to git)
    db_path: Path = Path("data/highlights.db")
    state_path: Path = Path("data/state.enc")
    state_key: SecretStr | None = None

    # Digest
    digest_size: int = Field(default=5, ge=1, le=50)
    require_keywords: bool = True
    favorite_weight: float = Field(default=3.0, gt=0)
    cooldown_days: int = Field(default=60, ge=0)
    max_per_book: int = Field(default=2, ge=1)
    timezone: str = "Europe/Amsterdam"
    send_time: time = time(7, 30)

    # Email (Gmail: smtp.gmail.com:465 with an App Password)
    smtp_host: str = "smtp.gmail.com"
    smtp_port: int = 465
    smtp_user: str | None = None
    smtp_password: SecretStr | None = None
    email_from: str | None = None
    email_to: str | None = None


@lru_cache
def get_settings() -> Settings:
    return Settings()  # type: ignore[call-arg]
