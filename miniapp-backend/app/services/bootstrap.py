from sqlalchemy import select
from sqlalchemy.orm import Session

from app.config import settings
from app.database import Base, engine
from app.models import TariffPlan, TelegramBot


DEFAULT_PLANS = [
    {
        "name": "1 ссылка / 7 дней",
        "description": "Мониторинг 1 ссылки на 7 дней",
        "links_limit": 1,
        "duration_days": 7,
        "price_rub": 100,
    },
    {
        "name": "1 ссылка / 30 дней",
        "description": "Мониторинг 1 ссылки на 30 дней",
        "links_limit": 1,
        "duration_days": 30,
        "price_rub": 500,
    },
    {
        "name": "3 ссылки / 7 дней",
        "description": "Мониторинг до 3 ссылок на 7 дней",
        "links_limit": 3,
        "duration_days": 7,
        "price_rub": 250,
    },
]


def init_db() -> None:
    Base.metadata.create_all(bind=engine)
    with engine.begin() as conn:
        conn.exec_driver_sql("ALTER TABLE users ADD COLUMN IF NOT EXISTS referral_code VARCHAR(64)")
        conn.exec_driver_sql("ALTER TABLE users ADD COLUMN IF NOT EXISTS referral_balance_rub INTEGER DEFAULT 0")
        conn.exec_driver_sql("CREATE UNIQUE INDEX IF NOT EXISTS uq_users_referral_code ON users (referral_code)")
        conn.exec_driver_sql("UPDATE users SET referral_code = 'ref_' || telegram_id::text WHERE referral_code IS NULL")
        conn.exec_driver_sql("UPDATE users SET referral_balance_rub = 0 WHERE referral_balance_rub IS NULL")

        conn.exec_driver_sql("ALTER TABLE monitorings ADD COLUMN IF NOT EXISTS bot_id INTEGER")
        conn.exec_driver_sql("ALTER TABLE monitorings ADD COLUMN IF NOT EXISTS link_configured BOOLEAN DEFAULT FALSE")
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

        conn.exec_driver_sql("ALTER TABLE telegram_bots ADD COLUMN IF NOT EXISTS is_primary BOOLEAN DEFAULT FALSE")
        conn.exec_driver_sql("UPDATE telegram_bots SET is_primary = FALSE WHERE is_primary IS NULL")
        conn.exec_driver_sql(
            "WITH first_bot AS (SELECT id FROM telegram_bots ORDER BY id ASC LIMIT 1) "
            "UPDATE telegram_bots SET is_primary = TRUE "
            "WHERE id = (SELECT id FROM first_bot) "
            "AND NOT EXISTS (SELECT 1 FROM telegram_bots WHERE is_primary IS TRUE)"
        )


def seed_default_plans(db: Session) -> None:
    for plan in DEFAULT_PLANS:
        existing = db.scalar(select(TariffPlan).where(TariffPlan.name == plan["name"]))
        if existing:
            continue
        db.add(TariffPlan(**plan))

    default_token = (settings.default_bot_token or "").strip()
    if default_token and default_token != "change_me_telegram_bot_token":
        existing_bot = db.scalar(select(TelegramBot).where(TelegramBot.bot_token == default_token))
        if not existing_bot:
            db.add(
                TelegramBot(
                    name=settings.default_bot_name,
                    bot_token=default_token,
                    is_active=True,
                    is_primary=True,
                )
            )
    db.commit()
