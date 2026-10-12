"""Typed settings for every service. Secrets are SecretStr, so they never print by accident."""

from functools import lru_cache

from pydantic import SecretStr
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        secrets_dir="/run/secrets",  # container secret files are read from here
        extra="ignore",
    )

    environment: str = "dev"
    demo_token: SecretStr  # from env DEMO_TOKEN, or the file /run/secrets/demo_token


@lru_cache
def get_settings() -> Settings:
    return Settings()
