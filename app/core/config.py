import json
from typing import Annotated, Self

from pydantic import Field, field_validator, model_validator
from pydantic_settings import BaseSettings, NoDecode, SettingsConfigDict


def _parse_string_list(value: object, setting: str) -> list[str]:
    """Normalize a JSON list or comma-separated environment value.

    :param value: Environment value or Python list.
    :param setting: Setting name for validation errors.
    :return: Stripped strings, or an empty list for empty input.
    """
    if value is None or value == "":
        return []
    if isinstance(value, str):
        if value.lstrip().startswith("["):
            # A value that looks like a JSON list must be one; splitting it would silently mangle entries.
            try:
                value = json.loads(value)
            except json.JSONDecodeError as exc:
                raise ValueError(f"{setting} must be a JSON list of strings") from exc
        else:
            value = value.split(",")
    if not isinstance(value, list) or not all(isinstance(item, str) for item in value):
        raise ValueError(f"{setting} must be a list of strings or comma-separated string")
    return [item.strip() for item in value if item.strip()]


class Settings(BaseSettings):
    API_KEYS: dict = {}
    INTERNAL_API_KEY: str | None = None

    SENTRY_DSN: str | None = None

    REDIS_HOST: str = "localhost"
    REDIS_PORT: int = 6379
    REDIS_PASSWORD: str | None = None

    ENABLE_DATABASE: bool = False
    DATABASE_URL: str | None = None

    ENABLE_CACHE: bool = False
    ENABLE_ID_MAPPING: bool = False

    ENABLE_LIVE_PUSH: bool = False
    APNS_CREDENTIALS_FILE: str | None = None
    GOOGLE_APPLICATION_CREDENTIALS: str | None = None
    VIDEO_TOKEN_FILE: str | None = None

    USER_AGENTS: Annotated[list[str], NoDecode] = ["val-esports-app/1.0"]
    HTTP_LOCAL_ADDRESSES: Annotated[list[str], NoDecode] = []
    VLR_REQUEST_INTERVAL_SECONDS: float = Field(default=1.0, ge=0)

    TIMEZONE: str = "America/New_York"
    DETECT_SOURCE_TIMEZONE: bool = True

    # Optional standalone prediction service; predict falls back to Elo when unset or unreachable.
    PREDICTION_SERVICE_URL: str | None = None

    # Riot esports API key; with LLM_API_KEY, a cron links each Riot tournament game to its VLR map and stores it.
    RIOT_API_KEY: str | None = None

    LLM_API_KEY: str | None = None
    LLM_BASE_URL: str | None = None
    LLM_MODEL: str = "gpt-5.4"
    LLM_REASONING_EFFORT: str | None = "low"
    LLM_DEBUG: bool = False
    LLM_MAX_STEPS: int = 10
    LLM_MAX_TOOL_CALLS: int = 12
    LLM_RATE_LIMIT_ENABLED: bool = False
    LLM_RATE_LIMIT: int = 5
    LLM_RATE_LIMIT_WINDOW: int = 60
    # Match insights: LLM-written pre- and post-match summaries (also need LLM_API_KEY), the time a
    # match-details request waits for generation (the app times out at 20 s), and each summary call's
    # own limit, which a generation that outlives the request still honours.
    ENABLE_MATCH_SUMMARIES: bool = False
    INSIGHTS_REQUEST_BUDGET_SECONDS: float = 12.0
    SUMMARY_TIMEOUT_SECONDS: float = 45.0

    model_config = SettingsConfigDict(env_file=".env")

    @field_validator("USER_AGENTS", mode="before")
    @classmethod
    def parse_user_agents(cls, value: object) -> list[str]:
        """Normalize configured user agents from an environment value.

        JSON is the reliable format for user agents containing commas.

        :param value: Comma-separated user agents or a JSON list of user agents.
        :return: Nonempty, stripped user agents.
        """
        agents = _parse_string_list(value, "USER_AGENTS")
        if not agents:
            raise ValueError("USER_AGENTS must list at least one user agent")
        return agents

    @field_validator("HTTP_LOCAL_ADDRESSES", mode="before")
    @classmethod
    def parse_http_local_addresses(cls, value: object) -> list[str]:
        """Normalize local interface addresses from an environment value.

        :param value: Comma-separated addresses or a JSON list of addresses.
        :return: Nonempty, stripped addresses.
        """
        return _parse_string_list(value, "HTTP_LOCAL_ADDRESSES")

    @model_validator(mode="after")
    def validate_features(self) -> Self:
        """Validate the services required by explicitly enabled features.

        :return: The validated settings.
        :raises ValueError: If an enabled feature is missing a required service or credential.
        """
        if self.ENABLE_DATABASE and not self.DATABASE_URL:
            raise ValueError("ENABLE_DATABASE requires DATABASE_URL")
        if self.ENABLE_ID_MAPPING and not self.ENABLE_CACHE:
            raise ValueError("ENABLE_ID_MAPPING requires ENABLE_CACHE")
        if self.ENABLE_LIVE_PUSH and not self.ENABLE_DATABASE:
            raise ValueError("ENABLE_LIVE_PUSH requires ENABLE_DATABASE")
        if self.ENABLE_LIVE_PUSH and not self.API_KEYS:
            raise ValueError("ENABLE_LIVE_PUSH requires API_KEYS")
        return self

    @property
    def needs_worker(self) -> bool:
        """Return whether an enabled feature needs the arq worker."""
        return self.ENABLE_CACHE or self.ENABLE_LIVE_PUSH

    @property
    def needs_redis(self) -> bool:
        """Return whether an enabled feature needs Redis."""
        return (
            self.needs_worker
            or self.LLM_RATE_LIMIT_ENABLED
            or (self.ENABLE_DATABASE and (bool(self.PREDICTION_SERVICE_URL) or self.match_summaries_enabled))
        )

    @property
    def match_summaries_enabled(self) -> bool:
        """Return whether match insights include LLM-written summaries."""
        return self.ENABLE_MATCH_SUMMARIES and bool(self.LLM_API_KEY)


settings = Settings()
