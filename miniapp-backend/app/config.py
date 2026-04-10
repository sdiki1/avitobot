from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    app_name: str = "Avito Monitor Backend"
    database_url: str = "postgresql+psycopg://avito:avito@db:5432/avito_bot"
    cors_origins: str = "*"
    admin_api_token: str = "change_me_admin_token"
    internal_api_token: str = "change_me_internal_token"
    miniapp_auth_secret: str = "change_me_miniapp_auth_secret"
    default_bot_token: str | None = Field(default=None, validation_alias="BOT_TOKEN")
    default_bot_name: str = "Основной бот"


settings = Settings()
