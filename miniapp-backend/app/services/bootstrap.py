from sqlalchemy import select
from sqlalchemy.orm import Session

from app.database import Base, engine
from app.models import TariffPlan


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


def seed_default_plans(db: Session) -> None:
    for plan in DEFAULT_PLANS:
        existing = db.scalar(select(TariffPlan).where(TariffPlan.name == plan["name"]))
        if existing:
            continue
        db.add(TariffPlan(**plan))
    db.commit()
