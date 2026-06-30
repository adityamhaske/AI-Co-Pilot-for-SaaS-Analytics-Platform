from pydantic_settings import BaseSettings, SettingsConfigDict
from typing import List


class Settings(BaseSettings):
    anthropic_api_key: str = ""
    jwt_secret: str = ""
    database_url: str = "sqlite:///./test.db"
    cors_origins: List[str] = ["http://localhost:6002"]

    model_config = SettingsConfigDict(env_file=".env", env_file_encoding="utf-8")


settings = Settings()
