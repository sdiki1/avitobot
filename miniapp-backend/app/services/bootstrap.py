import re

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.config import settings
from app.database import Base, engine
from app.models import AppSetting, ProxyConfig, TariffPlan, TelegramBot
from app.services.helpers import DEFAULT_TRIAL_DAYS, MINIAPP_CONTENT_DEFAULTS, TRIAL_DAYS_SETTING_KEY, normalize_proxy_url


DEFAULT_PLANS = [
    {
        "name": "Стандартная",
        "description": "Стандартная подписка",
        "links_limit": 1,
        "duration_days": 30,
        "price_rub": 500,
    },
    {
        "name": "Скоростная",
        "description": "Скоростная подписка",
        "links_limit": 1,
        "duration_days": 30,
        "price_rub": 500,
    },
]

ENV_PROXY_NAME_PREFIX = "env-proxy-"


def _parse_env_proxy_list(raw_value: str) -> list[str]:
    proxies: list[str] = []
    for candidate in re.split(r"[,\n;]", raw_value or ""):
        normalized = normalize_proxy_url(candidate)
        if normalized and normalized not in proxies:
            proxies.append(normalized)
    return proxies


def _build_env_proxy_name(taken_names: set[str], start_index: int) -> tuple[str, int]:
    index = max(1, int(start_index))
    while True:
        name = f"{ENV_PROXY_NAME_PREFIX}{index}"
        index += 1
        if name in taken_names:
            continue
        taken_names.add(name)
        return name, index


def _sync_env_proxies(db: Session) -> None:
    configured_proxy_urls = _parse_env_proxy_list(settings.parser_proxy_list)
    proxies = db.scalars(select(ProxyConfig).order_by(ProxyConfig.id.asc())).all()

    if not configured_proxy_urls:
        for proxy in proxies:
            if proxy.name.startswith(ENV_PROXY_NAME_PREFIX):
                proxy.is_active = False
        return

    normalized_to_proxy: dict[str, ProxyConfig] = {}
    for proxy in proxies:
        normalized = normalize_proxy_url(proxy.proxy_url)
        if normalized and normalized not in normalized_to_proxy:
            normalized_to_proxy[normalized] = proxy

    taken_names = {proxy.name for proxy in proxies}
    env_name_index = 1
    configured_ids: set[int] = set()

    for proxy_url in configured_proxy_urls:
        existing = normalized_to_proxy.get(proxy_url)
        if existing:
            existing.proxy_url = proxy_url
            existing.is_active = True
            configured_ids.add(existing.id)
            continue

        env_name, env_name_index = _build_env_proxy_name(taken_names, env_name_index)
        created = ProxyConfig(
            name=env_name,
            proxy_url=proxy_url,
            is_active=True,
        )
        db.add(created)
        db.flush()
        normalized_to_proxy[proxy_url] = created
        configured_ids.add(created.id)

    for proxy in proxies:
        if proxy.name.startswith(ENV_PROXY_NAME_PREFIX) and proxy.id not in configured_ids:
            proxy.is_active = False


def init_db() -> None:
    Base.metadata.create_all(bind=engine)
    with engine.begin() as conn:
        conn.exec_driver_sql("ALTER TABLE users ADD COLUMN IF NOT EXISTS referral_code VARCHAR(64)")
        conn.exec_driver_sql("ALTER TABLE users ADD COLUMN IF NOT EXISTS referral_balance_rub INTEGER DEFAULT 0")
        conn.exec_driver_sql("ALTER TABLE users ADD COLUMN IF NOT EXISTS referred_by_user_id INTEGER")
        conn.exec_driver_sql("CREATE INDEX IF NOT EXISTS ix_users_referred_by_user_id ON users (referred_by_user_id)")
        conn.exec_driver_sql("CREATE UNIQUE INDEX IF NOT EXISTS uq_users_referral_code ON users (referral_code)")
        conn.exec_driver_sql("UPDATE users SET referral_code = 'ref_' || telegram_id::text WHERE referral_code IS NULL")
        conn.exec_driver_sql("UPDATE users SET referral_balance_rub = 0 WHERE referral_balance_rub IS NULL")

        conn.exec_driver_sql("ALTER TABLE monitorings ADD COLUMN IF NOT EXISTS bot_id INTEGER")
        conn.exec_driver_sql("ALTER TABLE monitorings ADD COLUMN IF NOT EXISTS link_configured BOOLEAN DEFAULT FALSE")
        conn.exec_driver_sql("ALTER TABLE monitorings ADD COLUMN IF NOT EXISTS include_photo BOOLEAN DEFAULT TRUE")
        conn.exec_driver_sql("ALTER TABLE monitorings ADD COLUMN IF NOT EXISTS include_description BOOLEAN DEFAULT TRUE")
        conn.exec_driver_sql("ALTER TABLE monitorings ADD COLUMN IF NOT EXISTS include_seller_info BOOLEAN DEFAULT TRUE")
        conn.exec_driver_sql("ALTER TABLE monitorings ADD COLUMN IF NOT EXISTS notify_price_drop BOOLEAN DEFAULT TRUE")
        conn.exec_driver_sql("ALTER TABLE monitorings ADD COLUMN IF NOT EXISTS notify_since_at TIMESTAMP WITH TIME ZONE")
        conn.exec_driver_sql("CREATE INDEX IF NOT EXISTS ix_monitorings_bot_id ON monitorings (bot_id)")
        conn.exec_driver_sql(
            "CREATE UNIQUE INDEX IF NOT EXISTS uq_monitorings_user_bot "
            "ON monitorings (user_id, bot_id) WHERE bot_id IS NOT NULL"
        )
        conn.exec_driver_sql(
            "UPDATE monitorings SET link_configured = TRUE "
            "WHERE link_configured IS NOT TRUE AND NULLIF(TRIM(url), '') IS NOT NULL"
        )
        conn.exec_driver_sql("UPDATE monitorings SET link_configured = FALSE WHERE link_configured IS NULL")
        conn.exec_driver_sql("UPDATE monitorings SET include_photo = TRUE WHERE include_photo IS NULL")
        conn.exec_driver_sql("UPDATE monitorings SET include_description = TRUE WHERE include_description IS NULL")
        conn.exec_driver_sql("UPDATE monitorings SET include_seller_info = TRUE WHERE include_seller_info IS NULL")
        conn.exec_driver_sql("UPDATE monitorings SET notify_price_drop = TRUE WHERE notify_price_drop IS NULL")

        conn.exec_driver_sql("ALTER TABLE telegram_bots ADD COLUMN IF NOT EXISTS is_primary BOOLEAN DEFAULT FALSE")
        conn.exec_driver_sql("UPDATE telegram_bots SET is_primary = FALSE WHERE is_primary IS NULL")
        conn.exec_driver_sql(
            "WITH first_bot AS (SELECT id FROM telegram_bots ORDER BY id ASC LIMIT 1) "
            "UPDATE telegram_bots SET is_primary = TRUE "
            "WHERE id = (SELECT id FROM first_bot) "
            "AND NOT EXISTS (SELECT 1 FROM telegram_bots WHERE is_primary IS TRUE)"
        )

        conn.exec_driver_sql("ALTER TABLE user_subscriptions ADD COLUMN IF NOT EXISTS is_trial BOOLEAN DEFAULT FALSE")
        conn.exec_driver_sql("UPDATE user_subscriptions SET is_trial = FALSE WHERE is_trial IS NULL")

        conn.exec_driver_sql("ALTER TABLE proxies ADD COLUMN IF NOT EXISTS cooldown_until TIMESTAMP WITH TIME ZONE")
        conn.exec_driver_sql("ALTER TABLE proxies ADD COLUMN IF NOT EXISTS last_blocked_at TIMESTAMP WITH TIME ZONE")
        conn.exec_driver_sql("ALTER TABLE proxies ADD COLUMN IF NOT EXISTS last_block_status INTEGER")
        conn.exec_driver_sql("ALTER TABLE proxies ADD COLUMN IF NOT EXISTS expires_on DATE")
        conn.exec_driver_sql("ALTER TABLE proxies ADD COLUMN IF NOT EXISTS expiry_notified_at TIMESTAMP WITH TIME ZONE")


def seed_default_plans(db: Session) -> None:
    for plan in DEFAULT_PLANS:
        existing = db.scalar(select(TariffPlan).where(TariffPlan.name == plan["name"]))
        if existing:
            continue
        db.add(TariffPlan(**plan))

    default_token = (settings.default_bot_token or "").strip()
    default_name = (settings.default_bot_name or "Основной бот").strip() or "Основной бот"
    if default_token and default_token != "change_me_telegram_bot_token":
        existing_by_token = db.scalar(select(TelegramBot).where(TelegramBot.bot_token == default_token))
        if existing_by_token:
            existing_by_token.is_active = True
            if existing_by_token.name != default_name:
                duplicate_name = db.scalar(
                    select(TelegramBot.id).where(
                        TelegramBot.name == default_name,
                        TelegramBot.id != existing_by_token.id,
                    )
                )
                if not duplicate_name:
                    existing_by_token.name = default_name
        else:
            existing_by_name = db.scalar(select(TelegramBot).where(TelegramBot.name == default_name))
            if existing_by_name:
                duplicate_token = db.scalar(
                    select(TelegramBot.id).where(
                        TelegramBot.bot_token == default_token,
                        TelegramBot.id != existing_by_name.id,
                    )
                )
                if not duplicate_token:
                    existing_by_name.bot_token = default_token
                existing_by_name.is_active = True
            else:
                db.add(
                    TelegramBot(
                        name=default_name,
                        bot_token=default_token,
                        is_active=True,
                        is_primary=True,
                    )
                )

    trial_setting = db.scalar(select(AppSetting).where(AppSetting.key == TRIAL_DAYS_SETTING_KEY))
    if not trial_setting:
        db.add(AppSetting(key=TRIAL_DAYS_SETTING_KEY, value=str(DEFAULT_TRIAL_DAYS)))

    existing_settings = {
        row.key: row.value
        for row in db.scalars(select(AppSetting).where(AppSetting.key.in_(list(MINIAPP_CONTENT_DEFAULTS.keys())))).all()
    }
    for key, default_value in MINIAPP_CONTENT_DEFAULTS.items():
        if key in existing_settings:
            continue
        db.add(AppSetting(key=key, value=default_value))

    _sync_env_proxies(db)
    db.commit()
