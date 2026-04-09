from datetime import datetime, timedelta, timezone
import hashlib
import hmac

from sqlalchemy import Select, and_, select
from sqlalchemy.orm import Session

from app.config import settings
from app.models import Monitoring, TariffPlan, TelegramBot, User, UserSubscription


def now_utc() -> datetime:
    return datetime.now(timezone.utc)


def build_miniapp_auth_token(telegram_id: int) -> str:
    telegram_raw = str(telegram_id)
    signature = hmac.new(
        settings.miniapp_auth_secret.encode("utf-8"),
        telegram_raw.encode("utf-8"),
        hashlib.sha256,
    ).hexdigest()[:24]
    return f"{telegram_raw}.{signature}"


def parse_miniapp_auth_token(token: str) -> int | None:
    if not token or "." not in token:
        return None
    telegram_raw, signature = token.split(".", 1)
    if not telegram_raw.isdigit() or not signature:
        return None
    expected = hmac.new(
        settings.miniapp_auth_secret.encode("utf-8"),
        telegram_raw.encode("utf-8"),
        hashlib.sha256,
    ).hexdigest()[:24]
    if not hmac.compare_digest(signature, expected):
        return None
    return int(telegram_raw)


def generate_referral_code(telegram_id: int) -> str:
    return f"ref_{telegram_id}"


def ensure_user_referral_code(db: Session, user: User) -> User:
    if user.referral_code:
        return user
    user.referral_code = generate_referral_code(user.telegram_id)
    db.commit()
    db.refresh(user)
    return user


def get_or_create_user(db: Session, telegram_id: int, username: str | None, full_name: str | None) -> User:
    user = db.scalar(select(User).where(User.telegram_id == telegram_id))
    if user:
        if username is not None:
            user.username = username
        if full_name is not None:
            user.full_name = full_name
        if not user.referral_code:
            user.referral_code = generate_referral_code(telegram_id)
        db.commit()
        db.refresh(user)
        return user

    user = User(
        telegram_id=telegram_id,
        username=username,
        full_name=full_name,
        referral_code=generate_referral_code(telegram_id),
    )
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


def activate_user_subscription(db: Session, user_id: int, plan: TariffPlan) -> UserSubscription:
    active_sub = db.scalar(get_active_subscription_query(user_id))
    if active_sub:
        active_sub.status = "expired"

    started = now_utc()
    new_sub = UserSubscription(
        user_id=user_id,
        plan_id=plan.id,
        status="active",
        amount_paid=plan.price_rub,
        started_at=started,
        ends_at=add_days(started, plan.duration_days),
    )
    db.add(new_sub)
    db.commit()
    db.refresh(new_sub)
    return new_sub


def get_available_bot_for_user(db: Session, user_id: int) -> TelegramBot | None:
    bots = db.scalars(select(TelegramBot).where(TelegramBot.is_active.is_(True)).order_by(TelegramBot.id.asc())).all()
    if not bots:
        return None

    used_bot_ids = {
        bot_id
        for bot_id in db.scalars(
            select(Monitoring.bot_id).where(and_(Monitoring.user_id == user_id, Monitoring.bot_id.is_not(None)))
        ).all()
        if bot_id is not None
    }
    for bot in bots:
        if bot.id not in used_bot_ids:
            return bot
    return None


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
