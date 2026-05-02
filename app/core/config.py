from pydantic_settings import BaseSettings


class Settings(BaseSettings):
    app_name: str = "WorldNet"
    app_version: str = "0.1.0"
    database_url: str = "sqlite:///./worldnet.db"
    db_echo: bool = False
    log_level: str = "INFO"
    worldnewsapi_api_key: str | None = None
    worldnewsapi_base_url: str = "https://api.worldnewsapi.com"
    worldnewsapi_source_country: str = "us"
    worldnewsapi_language: str = "en"
    worldnewsapi_headlines_only: bool = False
    worldnewsapi_timeout_seconds: float = 30.0
    worldnewsapi_poll_interval_minutes: int = 30
    worldnewsapi_daily_request_budget: int = 50

    class Config:
        env_file = ".env"
        env_file_encoding = "utf-8"


settings = Settings()
