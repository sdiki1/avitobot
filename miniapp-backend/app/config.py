from pydantic import AliasChoices, Field
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
    miniapp_access_token_secret: str = Field(
        default="change_me_miniapp_access_secret",
        validation_alias=AliasChoices("MINIAPP_ACCESS_TOKEN_SECRET", "MINIAPP_JWT_ACCESS_SECRET"),
    )
    miniapp_refresh_token_secret: str = Field(
        default="change_me_miniapp_refresh_secret",
        validation_alias=AliasChoices("MINIAPP_REFRESH_TOKEN_SECRET", "MINIAPP_JWT_REFRESH_SECRET"),
    )
    miniapp_access_ttl_sec: int = 300
    miniapp_refresh_ttl_sec: int = 604800
    miniapp_initdata_ttl_sec: int = 300
    miniapp_auth_cookie_secure: bool = False
    miniapp_auth_cookie_samesite: str = "lax"
    miniapp_access_cookie_name: str = "miniapp_access_token"
    miniapp_refresh_cookie_name: str = "miniapp_refresh_token"
    proxy_block_cooldown_seconds: int | None = None
    proxy_block_cooldown_minutes: int | None = Field(default=None, validation_alias="PROXY_BLOCK_COOLDOWN_MINUTES")
    redis_url: str = "redis://redis:6379/0"
    redis_notify_queue_prefix: str = "notify:bot:"
    referral_reward_percent: int = 10
    admin_notify_chat_ids: str = ""
    speed_surcharge_7_days_rub: int = 300
    speed_surcharge_15_days_rub: int = 500
    speed_surcharge_30_days_rub: int = 800
    parser_proxy_list: str = ""

    @property
    def proxy_block_cooldown_total_seconds(self) -> int:
        if self.proxy_block_cooldown_seconds is not None:
            return max(1, int(self.proxy_block_cooldown_seconds))
        if self.proxy_block_cooldown_minutes is not None:
            return max(1, int(self.proxy_block_cooldown_minutes) * 60)
        return 3


settings = Settings()
