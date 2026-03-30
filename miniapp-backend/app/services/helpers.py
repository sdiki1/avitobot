from datetime import datetime, timedelta, timezone

from sqlalchemy import Select, and_, select
from sqlalchemy.orm import Session

from app.models import User, UserSubscription


def now_utc() -> datetime:
    return datetime.now(timezone.utc)


def get_or_create_user(db: Session, telegram_id: int, username: str | None, full_name: str | None) -> User:
    user = db.scalar(select(User).where(User.telegram_id == telegram_id))
    if user:
        if username is not None:
            user.username = username
        if full_name is not None:
            user.full_name = full_name
        db.commit()
        db.refresh(user)
        return user

    user = User(telegram_id=telegram_id, username=username, full_name=full_name)
    db.add(user)
    db.commit()
    db.refresh(user)
    return user


def get_active_subscription_query(user_id: int) -> Select[tuple[UserSubscription]]:
    return select(UserSubscription).where(
        and_(
            UserSubscription.user_id == user_id,
            UserSubscription.status == "active",
            UserSubscription.ends_at > now_utc(),
        )
    ).order_by(UserSubscription.ends_at.desc())


def seconds_to_human(delta_seconds: int) -> str:
    if delta_seconds <= 0:
        return "0с"
    minutes, seconds = divmod(delta_seconds, 60)
    hours, minutes = divmod(minutes, 60)
    if hours:
        return f"{hours}ч {minutes}м"
    if minutes:
        return f"{minutes}м {seconds}с"
    return f"{seconds}с"


def format_new_item_message(title: str, price_rub: int | None, url: str, location: str | None) -> str:
    price_line = f"{price_rub:,} ₽".replace(",", " ") if price_rub is not None else "Цена не указана"
    location_line = location or "Локация не указана"
    return (
        "🔔 Новое объявление Avito\n"
        f"{title}\n"
        f"💰 {price_line}\n"
        f"📍 {location_line}\n"
        f"🔗 {url}"
    )


def add_days(base: datetime, days: int) -> datetime:
    return base + timedelta(days=days)
