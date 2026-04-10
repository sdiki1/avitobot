from datetime import datetime, timedelta, timezone
import hashlib
import hmac
import json
import logging

import httpx
from sqlalchemy import Select, and_, func, select
from sqlalchemy.orm import Session

from app.config import settings
from app.models import AppSetting, Monitoring, TariffPlan, TelegramBot, User, UserSubscription

logger = logging.getLogger(__name__)
TRIAL_DAYS_SETTING_KEY = "trial_days"
DEFAULT_TRIAL_DAYS = 3

MINIAPP_CONTENT_DEFAULTS = {
    "miniapp_info_support_title": "Поддержка",
    "miniapp_info_support_url": "https://t.me/your_support",
    "miniapp_info_faq_title": "Частые вопросы",
    "miniapp_info_faq_url": "https://t.me/your_faq",
    "miniapp_info_news_title": "Новостной канал",
    "miniapp_info_news_url": "https://t.me/your_news",
    "miniapp_info_terms_title": "Пользовательское соглашение",
    "miniapp_info_terms_url": "https://t.me/your_terms",
    "miniapp_info_privacy_title": "Политика конфиденциальности",
    "miniapp_info_privacy_url": "https://t.me/your_privacy",
    "miniapp_subscriptions_title": "Подписки",
    "miniapp_subscriptions_hint": "Управление тарифом и переход к назначенным ботам.",
    "miniapp_profile_title": "Профиль",
}


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


def activate_user_subscription(
    db: Session,
    user_id: int,
    plan: TariffPlan,
    *,
    duration_days_override: int | None = None,
    amount_paid_override: int | None = None,
    is_trial: bool = False,
) -> UserSubscription:
    active_sub = db.scalar(get_active_subscription_query(user_id))
    if active_sub:
        active_sub.status = "expired"

    started = now_utc()
    duration_days = duration_days_override if duration_days_override is not None else plan.duration_days
    amount_paid = amount_paid_override if amount_paid_override is not None else plan.price_rub
    new_sub = UserSubscription(
        user_id=user_id,
        plan_id=plan.id,
        status="active",
        is_trial=is_trial,
        amount_paid=amount_paid,
        started_at=started,
        ends_at=add_days(started, duration_days),
    )
    db.add(new_sub)
    db.commit()
    db.refresh(new_sub)
    return new_sub


def get_available_bot_for_user(db: Session, user_id: int) -> TelegramBot | None:
    bots = db.scalars(
        select(TelegramBot)
        .where(
            and_(
                TelegramBot.is_active.is_(True),
                TelegramBot.is_primary.is_(False),
            )
        )
        .order_by(TelegramBot.id.asc())
    ).all()
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


def ensure_subscription_monitoring_slots(db: Session, user_id: int, links_limit: int) -> int:
    target_slots = max(0, int(links_limit))
    if target_slots == 0:
        return 0

    existing_total = db.scalar(select(func.count(Monitoring.id)).where(Monitoring.user_id == user_id)) or 0
    if existing_total >= target_slots:
        return 0

    created = 0
    for slot_index in range(existing_total, target_slots):
        bot = get_available_bot_for_user(db, user_id)
        if not bot:
            break
        db.add(
            Monitoring(
                user_id=user_id,
                bot_id=bot.id,
                url="https://www.avito.ru/",
                title=f"Мониторинг #{slot_index + 1}",
                keywords_white="",
                keywords_black="",
                min_price=None,
                max_price=None,
                geo=None,
                is_active=False,
                link_configured=False,
            )
        )
        db.flush()
        created += 1

    if created:
        db.commit()
    return created


def get_trial_days(db: Session) -> int:
    setting = db.scalar(select(AppSetting).where(AppSetting.key == TRIAL_DAYS_SETTING_KEY))
    if not setting:
        return DEFAULT_TRIAL_DAYS
    try:
        trial_days = int(setting.value)
    except (TypeError, ValueError):
        return 0
    return max(0, trial_days)


def set_trial_days(db: Session, trial_days: int) -> int:
    normalized = max(0, int(trial_days))
    setting = db.scalar(select(AppSetting).where(AppSetting.key == TRIAL_DAYS_SETTING_KEY))
    if not setting:
        setting = AppSetting(key=TRIAL_DAYS_SETTING_KEY, value=str(normalized))
        db.add(setting)
    else:
        setting.value = str(normalized)
    db.commit()
    return normalized


def get_miniapp_content_settings(db: Session) -> dict[str, str]:
    keys = list(MINIAPP_CONTENT_DEFAULTS.keys())
    rows = db.scalars(select(AppSetting).where(AppSetting.key.in_(keys))).all()
    values = {row.key: row.value for row in rows}
    return {
        key: (values.get(key) if values.get(key) not in (None, "") else default)
        for key, default in MINIAPP_CONTENT_DEFAULTS.items()
    }


def set_miniapp_content_settings(db: Session, updates: dict[str, str]) -> dict[str, str]:
    if not updates:
        return get_miniapp_content_settings(db)

    keys = [key for key in updates.keys() if key in MINIAPP_CONTENT_DEFAULTS]
    if not keys:
        return get_miniapp_content_settings(db)

    rows = db.scalars(select(AppSetting).where(AppSetting.key.in_(keys))).all()
    existing_by_key = {row.key: row for row in rows}

    for key in keys:
        raw_value = updates.get(key, "")
        normalized = (raw_value or "").strip()
        value = normalized if normalized else MINIAPP_CONTENT_DEFAULTS[key]
        row = existing_by_key.get(key)
        if row:
            row.value = value
        else:
            db.add(AppSetting(key=key, value=value))

    db.commit()
    return get_miniapp_content_settings(db)


def _send_telegram_message(bot_token: str, chat_id: int, text: str) -> bool:
    try:
        proxy = (settings.telegram_socks_proxy or "").strip() or None
        with httpx.Client(timeout=10, proxy=proxy) as client:
            response = client.post(
                f"https://api.telegram.org/bot{bot_token}/sendMessage",
                json={
                    "chat_id": chat_id,
                    "text": text,
                    "disable_web_page_preview": True,
                },
            )
            return 200 <= response.status_code < 300
    except Exception as exc:
        logger.warning("Failed to send telegram message: %s", exc)
        return False


def send_subscription_assigned_bot_message(db: Session, user: User) -> bool:
    primary_bot = db.scalar(
        select(TelegramBot)
        .where(and_(TelegramBot.is_primary.is_(True), TelegramBot.is_active.is_(True)))
        .order_by(TelegramBot.id.asc())
    )
    if not primary_bot:
        primary_bot = db.scalar(select(TelegramBot).where(TelegramBot.is_active.is_(True)).order_by(TelegramBot.id.asc()))
    if not primary_bot:
        return False

    assigned_bot = db.scalar(
        select(TelegramBot)
        .join(Monitoring, Monitoring.bot_id == TelegramBot.id)
        .where(
            and_(
                Monitoring.user_id == user.id,
                TelegramBot.is_primary.is_(False),
                TelegramBot.is_active.is_(True),
            )
        )
        .order_by(Monitoring.id.asc())
    )
    if not assigned_bot:
        return False

    nickname = assigned_bot.bot_username or assigned_bot.name
    nickname = nickname.lstrip("@")
    text = (
        f"Вам назначен бот: @{nickname}. "
        "Перейдите в него и можете начинать работу с мониторингом"
    )
    return _send_telegram_message(primary_bot.bot_token, user.telegram_id, text)


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
