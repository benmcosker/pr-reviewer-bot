"""Application configuration, loaded from the environment / a .env file.

Settings are resolved lazily via :func:`get_settings` so that importing any
module does not require secrets to be present — useful for tests and for booting
the app before a job actually needs credentials.
"""

from functools import lru_cache

from pydantic_settings import BaseSettings, SettingsConfigDict

DEFAULT_SKIP_GLOBS = [
    "*.lock",
    "package-lock.json",
    "yarn.lock",
    "poetry.lock",
    "*.min.js",
    "*.svg",
    "*.png",
    "*.jpg",
    "*.jpeg",
    "*.gif",
    "*.pdf",
    "vendor/*",
    "node_modules/*",
    "dist/*",
    "build/*",
]


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=".env", env_file_encoding="utf-8", extra="ignore"
    )

    # GitHub App credentials
    github_app_id: int = 0
    github_private_key: str = ""
    github_webhook_secret: str = ""

    # Claude API
    anthropic_api_key: str | None = None
    review_model: str = "claude-opus-4-8"

    # Tunables
    max_files_per_pr: int = 40
    max_nits_per_file: int = 3
    skip_globs: list[str] = DEFAULT_SKIP_GLOBS
    request_timeout: float = 30.0
    max_http_retries: int = 4


@lru_cache
def get_settings() -> Settings:
    return Settings()
