from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", env_file_encoding="utf-8")

    app_name: str = "WorldNet"
    app_version: str = "0.1.0"
    database_url: str = "sqlite:///./worldnet.db"
    db_echo: bool = False
    log_level: str = "INFO"
    api_access_key: str | None = None
    rsshub_base_url: str = "http://localhost:1200"
    rsshub_access_key: str | None = None
    rsshub_timeout_seconds: float = 30.0
    rsshub_cls_telegraph_enabled: bool = True
    rsshub_cls_telegraph_poll_interval_minutes: int = 5
    rsshub_cls_depth_enabled: bool = True
    rsshub_cls_depth_poll_interval_minutes: int = 30
    scheduler_enabled: bool = True
    scheduler_tick_seconds: float = 5.0
    scheduler_timezone: str = "Asia/Shanghai"
    scheduler_tasks_default_dir: str = "config/tasks/default"
    scheduler_tasks_custom_dir: str = "config/tasks/custom"
    notification_config_default_dir: str = "config/notifications/default"
    notification_config_custom_dir: str = "config/notifications/custom"
    worldnewsapi_api_key: str | None = None
    worldnewsapi_base_url: str = "https://api.worldnewsapi.com"
    worldnewsapi_enabled: bool = False
    worldnewsapi_source_country: str = "us"
    worldnewsapi_language: str = "en"
    worldnewsapi_headlines_only: bool = False
    worldnewsapi_timeout_seconds: float = 30.0
    worldnewsapi_poll_interval_minutes: int = 30
    worldnewsapi_daily_request_budget: int = 50
    qq_agent_mail_enabled: bool = False
    qq_agent_mail_to: str | None = None
    qq_agent_mail_cli_command: str = "agently-cli"
    qq_agent_mail_timeout_seconds: float = 30.0
    qq_agent_mail_authorized_email: str | None = None
    hermes_send_command: str = "/usr/local/bin/worldnet-hermes-send"
    hermes_bridge_url: str = "http://host.docker.internal:15307/send"
    hermes_weixin_target: str | None = None
    hermes_send_timeout_seconds: float = 30.0


settings = Settings()
