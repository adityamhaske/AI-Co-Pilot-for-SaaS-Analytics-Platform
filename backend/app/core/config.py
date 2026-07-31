from typing import Literal

from pydantic import AliasChoices, Field, field_validator, model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict

# Anything shorter than this is not a credible HMAC key for HS256.
MIN_JWT_SECRET_LENGTH = 32

# Values that appear in .env.example, tutorials and CI configs. Refusing them by name
# stops the most common way a deployment ends up with a "secret" that every reader of
# the repository already knows.
FORBIDDEN_JWT_SECRETS = {
    "your_jwt_secret_here",
    "changeme",
    "secret",
    "test",
}


class Settings(BaseSettings):
    """Application configuration.

    Validation here is deliberately fail-fast: a misconfigured deployment should refuse
    to boot rather than start in an insecure state.

    The original default of ``jwt_secret = ""`` was a critical hole, because the
    then-current python-jose signed *and* verified with an empty key — any visitor to a
    default deployment could mint an admin token for any tenant. PyJWT rejects an empty
    HMAC key outright, so that exact hole is now closed twice over. These checks remain
    the right guard regardless: they turn a misconfiguration into a clear refusal at boot
    rather than a 500 on the first login, and they also catch short and placeholder
    secrets, which no library will reject for you.
    """

    environment: Literal["development", "test", "production"] = "development"

    # Which model provider answers questions. Only the selected provider's SDK and key
    # are required; the others can be absent entirely.
    llm_provider: Literal["anthropic", "openai", "gemini"] = "anthropic"
    #: Override the provider's default model. Blank means the provider's default.
    llm_model: str = ""

    # Each key accepts the vendor's own conventional variable name as well as ours.
    # GOOGLE_API_KEY in particular is what google-genai reads by default, so a key
    # already exported for the Google SDK works here without being renamed.
    anthropic_api_key: str = Field(
        default="",
        validation_alias=AliasChoices("ANTHROPIC_API_KEY", "CLAUDE_API_KEY"),
    )
    openai_api_key: str = Field(
        default="", validation_alias=AliasChoices("OPENAI_API_KEY")
    )
    gemini_api_key: str = Field(
        default="",
        validation_alias=AliasChoices("GEMINI_API_KEY", "GOOGLE_API_KEY"),
    )

    # JWT_SECRET_KEY is the more common spelling in the wild; accept both rather than
    # silently ignoring a secret someone has clearly set on purpose.
    jwt_secret: str = Field(
        default="", validation_alias=AliasChoices("JWT_SECRET", "JWT_SECRET_KEY")
    )
    database_url: str = "sqlite:///./test.db"
    cors_origins: list[str] = Field(default_factory=lambda: ["http://localhost:6002"])

    # Agent loop bounds. These cap the blast radius of a single request: without them the
    # orchestrator's tool loop could run indefinitely on the caller's behalf, at the
    # operator's expense.
    max_agent_steps: int = 6
    max_tokens_per_turn: int = 1024
    #: Deadline for a single provider HTTP request, passed to the SDK.
    provider_timeout_seconds: float = 60.0
    #: Total wall clock for one question. Checked between agent steps, so a step already
    #: in flight finishes; the per-request timeout above bounds that step.
    agent_timeout_seconds: float = 120.0

    # Row-level security in PostgreSQL, as a second layer behind the application-side
    # tenant filter. Requires the API to connect as a role that does not own the tables,
    # because PostgreSQL exempts the owner. Off by default so local SQLite development and
    # the test suite are unaffected.
    enable_row_level_security: bool = False

    # Rolling 24-hour spend ceiling per user, in USD. Rate limiting bounds request
    # count; this bounds actual cost.
    daily_cost_limit_usd: float = 2.00

    # Token lifetimes.
    access_token_ttl_minutes: int = Field(
        default=15,
        validation_alias=AliasChoices(
            "ACCESS_TOKEN_TTL_MINUTES", "JWT_ACCESS_TOKEN_EXPIRE_MINUTES"
        ),
    )
    refresh_token_ttl_days: int = Field(
        default=7,
        validation_alias=AliasChoices(
            "REFRESH_TOKEN_TTL_DAYS", "JWT_REFRESH_TOKEN_EXPIRE_DAYS"
        ),
    )

    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
        populate_by_name=True,
    )

    @property
    def is_production(self) -> bool:
        return self.environment == "production"

    @field_validator("cors_origins")
    @classmethod
    def reject_wildcard_origin(cls, v: list[str]) -> list[str]:
        # allow_credentials=True with a wildcard origin is rejected by browsers anyway,
        # and signals that the operator meant to allow everything. Fail loudly instead.
        if "*" in v:
            raise ValueError(
                "cors_origins may not contain '*': the API sends credentials, so every "
                "allowed origin must be listed explicitly."
            )
        return v

    @model_validator(mode="after")
    def validate_secrets(self) -> "Settings":
        # The test environment substitutes a strong deterministic secret so the suite is
        # hermetic. It *overrides* rather than only filling a blank: a developer's .env
        # usually still holds the placeholder, and running tests against a 20-byte key
        # made PyJWT warn on every token while proving nothing.
        if self.environment == "test":
            weak = (
                not self.jwt_secret
                or self.jwt_secret.lower() in FORBIDDEN_JWT_SECRETS
                or len(self.jwt_secret) < MIN_JWT_SECRET_LENGTH
            )
            if weak:
                object.__setattr__(self, "jwt_secret", "test-only-" + "k" * 40)
            return self

        secret = self.jwt_secret or ""
        if not secret:
            raise ValueError(
                "JWT_SECRET is not set. Generate one with:\n"
                "  python -c 'import secrets; print(secrets.token_urlsafe(48))'"
            )
        if secret.lower() in FORBIDDEN_JWT_SECRETS:
            raise ValueError(
                f"JWT_SECRET is set to the placeholder value {secret!r}. Generate a real "
                "one with:\n"
                "  python -c 'import secrets; print(secrets.token_urlsafe(48))'"
            )
        if len(secret) < MIN_JWT_SECRET_LENGTH:
            raise ValueError(
                f"JWT_SECRET must be at least {MIN_JWT_SECRET_LENGTH} characters "
                f"(got {len(secret)})."
            )

        if self.is_production:
            if self.database_url.startswith("sqlite"):
                raise ValueError(
                    "DATABASE_URL points at SQLite in production. SQLite is single-writer "
                    "and lives on ephemeral container disk; use PostgreSQL."
                )
            required_key = {
                "anthropic": ("ANTHROPIC_API_KEY", self.anthropic_api_key),
                "openai": ("OPENAI_API_KEY", self.openai_api_key),
                "gemini": ("GEMINI_API_KEY", self.gemini_api_key),
            }[self.llm_provider]
            if not required_key[1]:
                raise ValueError(
                    f"{required_key[0]} is required in production when "
                    f"LLM_PROVIDER={self.llm_provider}."
                )

        return self


settings = Settings()
