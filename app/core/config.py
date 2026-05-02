from pydantic_settings import BaseSettings


class Settings(BaseSettings):
    app_name: str = "WorldNet Stock Radar"
    app_version: str = "0.1.0"
    database_url: str = "sqlite:///./worldnet.db"
    db_echo: bool = False
    log_level: str = "INFO"

    class Config:
        env_file = ".env"
        env_file_encoding = "utf-8"


settings = Settings()
