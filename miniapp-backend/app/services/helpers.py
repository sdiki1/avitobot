from datetime import datetime, timedelta, timezone
import hashlib
import hmac
import html
import json
import logging
import mimetypes
import re
from pathlib import Path
from typing import Any
from urllib import request as urllib_request
from urllib.parse import quote, urlsplit, urlunsplit
from uuid import uuid4

from sqlalchemy import Select, and_, func, or_, select
from sqlalchemy.orm import Session

from app.config import settings
from app.models import AppSetting, Monitoring, ProxyConfig, TariffPlan, TelegramBot, User, UserSubscription

logger = logging.getLogger(__name__)
TRIAL_DAYS_SETTING_KEY = "trial_days"
REFERRAL_REWARD_PERCENT_SETTING_KEY = "referral_reward_percent"
PROXY_CAPACITY_WARNING_SETTING_KEY = "proxy_capacity_last_warning_signature"
DEFAULT_TRIAL_DAYS = 3
BACKEND_ROOT = Path(__file__).resolve().parents[2]
PROJECT_ROOT = Path(__file__).resolve().parents[3]
PROMO_DISCOUNT_PERCENT = "percent"
PROMO_DISCOUNT_RUB = "rub"
PROMO_DISCOUNT_TYPES = {PROMO_DISCOUNT_PERCENT, PROMO_DISCOUNT_RUB}

MINIAPP_CONTENT_DEFAULTS = {
    "miniapp_info_support_title": "Поддержка",
    "miniapp_info_support_url": "https://t.me/your_support",
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
STATIC_MESSAGE_PHOTOS: dict[str, list[Path]] = {
    "error": [
        BACKEND_ROOT / "msg_error.jpeg",
        PROJECT_ROOT / "msg_error.jpeg",
    ],
    "link_change": [
        BACKEND_ROOT / "msg_link_change.jpeg",
        BACKEND_ROOT / "msg_link_change.jpg",
        BACKEND_ROOT / "msg_link_change.png",
        PROJECT_ROOT / "msg_link_change.jpeg",
        PROJECT_ROOT / "msg_link_change.jpg",
        PROJECT_ROOT / "msg_link_change.png",
    ],
    "monitoring_start": [
        BACKEND_ROOT / "msg_monitoring_start.jpeg",
        PROJECT_ROOT / "msg_monitoring_start.jpeg",
    ],
    "monitoring_stop": [
        BACKEND_ROOT / "msg_monitoring_stop.jpeg",
        BACKEND_ROOT / "msg_monitoring_stop.png",
        PROJECT_ROOT / "msg_monitoring_stop.jpeg",
        PROJECT_ROOT / "msg_monitoring_stop.png",
    ],
}
_logged_missing_static_photo_keys: set[str] = set()


def now_utc() -> datetime:
    return datetime.now(timezone.utc)


def normalize_monitoring_url(url: str | None) -> str:
    raw = (url or "").strip()
    if not raw:
        return ""

    try:
        parsed = urlsplit(raw)
    except Exception:
        return raw

    netloc = parsed.netloc or ""
    lower_netloc = netloc.lower()
    if lower_netloc == "m.avito.ru":
        replaced_netloc = "www.avito.ru"
    elif lower_netloc.startswith("m.avito.ru:"):
        replaced_netloc = "www.avito.ru" + netloc[len("m.avito.ru") :]
    else:
        return raw

    return urlunsplit((parsed.scheme, replaced_netloc, parsed.path, parsed.query, parsed.fragment))


def normalize_proxy_url(proxy_url: str | None) -> str:
    raw = (proxy_url or "").strip()
    if not raw:
        return ""

    if "://" in raw:
        return raw

    parts = raw.split(":")
    if len(parts) >= 4 and parts[1].isdigit():
        host = parts[0]
        port = parts[1]
        username = parts[2]
        password = ":".join(parts[3:])
        return f"socks5://{quote(username, safe='')}:{quote(password, safe='')}@{host}:{port}"

    if len(parts) == 2 and parts[1].isdigit():
        return f"http://{raw}"

    if "@" in raw:
        return f"http://{raw}"

    return raw


def normalize_promo_code(code: str | None) -> str:
    normalized = (code or "").strip().upper()
    normalized = re.sub(r"\s+", "", normalized)
    return normalized


def validate_promo_code_value(discount_type: str | None, discount_value: int | None) -> tuple[str, int]:
    normalized_type = (discount_type or "").strip().lower()
    if normalized_type in {"процент", "проценты", "percent", "percentage", "%"}:
        normalized_type = PROMO_DISCOUNT_PERCENT
    elif normalized_type in {"руб", "рубли", "ruble", "rubles", "rub"}:
        normalized_type = PROMO_DISCOUNT_RUB

    if normalized_type not in PROMO_DISCOUNT_TYPES:
        raise ValueError("Тип промокода должен быть percent или rub")

    value = int(discount_value or 0)
    if normalized_type == PROMO_DISCOUNT_PERCENT and not 1 <= value <= 100:
        raise ValueError("Процент скидки должен быть от 1 до 100")
    if normalized_type == PROMO_DISCOUNT_RUB and value <= 0:
        raise ValueError("Скидка в рублях должна быть больше 0")
    return normalized_type, value


def calculate_promo_discount_rub(discount_type: str, discount_value: int, base_price_rub: int) -> int:
    base_price = max(0, int(base_price_rub or 0))
    normalized_type, value = validate_promo_code_value(discount_type, discount_value)
    if normalized_type == PROMO_DISCOUNT_PERCENT:
        return min(base_price, int(base_price * value / 100))
    return min(base_price, value)


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


def _normalize_referral_code(value: str | None) -> str | None:
    normalized = (value or "").strip()
    return normalized or None


def apply_referral_code(db: Session, user: User, referral_code: str | None) -> bool:
    normalized = _normalize_referral_code(referral_code)
    if not normalized:
        return False
    if user.referred_by_user_id is not None:
        return False

    referrer = db.scalar(select(User).where(User.referral_code == normalized))
    if not referrer or referrer.id == user.id:
        return False

    user.referred_by_user_id = referrer.id
    db.commit()
    db.refresh(user)
    return True


def get_speed_surcharge_rub(duration_days: int) -> int:
    days = max(0, int(duration_days))
    if days <= 7:
        return max(0, int(settings.speed_surcharge_7_days_rub))
    if days <= 15:
        return max(0, int(settings.speed_surcharge_15_days_rub))
    return max(0, int(settings.speed_surcharge_30_days_rub))


def reward_referrer_for_payment(db: Session, paying_user: User, paid_amount_rub: int) -> int:
    if paid_amount_rub <= 0:
        return 0
    if paying_user.referred_by_user_id is None:
        return 0

    reward_percent = get_referral_reward_percent(db)
    if reward_percent <= 0:
        return 0

    referrer = db.get(User, int(paying_user.referred_by_user_id))
    if not referrer:
        return 0

    reward = int(paid_amount_rub * reward_percent / 100)
    if reward <= 0:
        return 0

    referrer.referral_balance_rub = int(referrer.referral_balance_rub or 0) + reward
    return reward


def get_active_subscription_query(user_id: int) -> Select[tuple[UserSubscription]]:
    return select(UserSubscription).where(
        and_(
            UserSubscription.user_id == user_id,
            UserSubscription.ends_at > now_utc(),
        )
    ).order_by(UserSubscription.ends_at.desc())


def get_monitoring_subscription_map(db: Session, user_id: int) -> dict[int, dict]:
    """Распределяет активные подписки по слотам ботов пользователя.

    Каждая подписка раскладывается в links_limit слотов, слоты сортируются по
    сроку окончания подписки (по убыванию — самые «свежие» вперед). Мониторинги
    с ботами сортируются по id asc и сопоставляются 1-к-1 со слотами.
    """
    subs = db.scalars(
        select(UserSubscription)
        .where(and_(UserSubscription.user_id == user_id, UserSubscription.ends_at > now_utc()))
        .order_by(UserSubscription.ends_at.desc())
    ).all()

    slots: list[dict] = []
    for sub in subs:
        limit = int(sub.plan.links_limit) if sub.plan and sub.plan.links_limit else 0
        for _ in range(limit):
            slots.append(
                {
                    "subscription_id": sub.id,
                    "subscription_ends_at": sub.ends_at,
                    "subscription_plan_name": sub.plan.name if sub.plan else "Без тарифа",
                    "subscription_is_trial": bool(sub.is_trial),
                }
            )

    monitorings = db.scalars(
        select(Monitoring)
        .where(and_(Monitoring.user_id == user_id, Monitoring.bot_id.is_not(None)))
        .order_by(Monitoring.id.asc())
    ).all()

    mapping: dict[int, dict] = {}
    for mon, slot in zip(monitorings, slots):
        mapping[int(mon.id)] = slot
    return mapping


def get_active_links_limit(db: Session, user_id: int) -> int:
    total = db.scalar(
        select(func.coalesce(func.sum(TariffPlan.links_limit), 0))
        .select_from(UserSubscription)
        .join(TariffPlan, UserSubscription.plan_id == TariffPlan.id, isouter=True)
        .where(
            and_(
                UserSubscription.user_id == user_id,
                UserSubscription.ends_at > now_utc(),
            )
        )
    )
    return max(0, int(total or 0))


def activate_user_subscription(
    db: Session,
    user_id: int,
    plan: TariffPlan,
    *,
    duration_days_override: int | None = None,
    amount_paid_override: int | None = None,
    is_trial: bool = False,
) -> UserSubscription:
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

    existing_total = db.scalar(
        select(func.count(Monitoring.id)).where(
            and_(
                Monitoring.user_id == user_id,
                Monitoring.bot_id.is_not(None),
            )
        )
    ) or 0
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


def get_referral_reward_percent(db: Session) -> int:
    setting = db.scalar(select(AppSetting).where(AppSetting.key == REFERRAL_REWARD_PERCENT_SETTING_KEY))
    if not setting:
        return max(0, min(100, int(settings.referral_reward_percent)))
    try:
        reward_percent = int(setting.value)
    except (TypeError, ValueError):
        return max(0, min(100, int(settings.referral_reward_percent)))
    return max(0, min(100, reward_percent))


def set_referral_reward_percent(db: Session, reward_percent: int) -> int:
    normalized = max(0, min(100, int(reward_percent)))
    setting = db.scalar(select(AppSetting).where(AppSetting.key == REFERRAL_REWARD_PERCENT_SETTING_KEY))
    if not setting:
        setting = AppSetting(key=REFERRAL_REWARD_PERCENT_SETTING_KEY, value=str(normalized))
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


def _send_telegram_message(
    bot_token: str,
    chat_id: int,
    text: str,
    *,
    reply_markup: dict[str, Any] | None = None,
    disable_web_page_preview: bool = True,
) -> bool:
    payload_data: dict[str, Any] = {
        "chat_id": chat_id,
        "text": text,
        "disable_web_page_preview": disable_web_page_preview,
    }
    if reply_markup:
        payload_data["reply_markup"] = reply_markup
    payload = json.dumps(payload_data).encode("utf-8")
    req = urllib_request.Request(
        f"https://api.telegram.org/bot{bot_token}/sendMessage",
        data=payload,
        headers={"Content-Type": "application/json"},
        method="POST",
    )
    try:
        with urllib_request.urlopen(req, timeout=10) as response:
            return 200 <= response.status < 300
    except Exception as exc:
        logger.warning("Failed to send telegram message: %s", exc)
        return False


def _resolve_static_photo_path(photo_key: str | None) -> Path | None:
    if not photo_key:
        return None
    candidates = STATIC_MESSAGE_PHOTOS.get(photo_key) or []
    for candidate in candidates:
        try:
            if candidate.exists() and candidate.is_file():
                return candidate
        except OSError:
            continue
    if photo_key not in _logged_missing_static_photo_keys:
        _logged_missing_static_photo_keys.add(photo_key)
        joined = ", ".join(str(path) for path in candidates) or "<none>"
        logger.warning("Static photo for key='%s' not found. Tried: %s", photo_key, joined)
    return None


def _send_telegram_photo(
    bot_token: str,
    chat_id: int,
    caption: str,
    photo_path: Path,
    *,
    reply_markup: dict[str, Any] | None = None,
) -> bool:
    try:
        photo_bytes = photo_path.read_bytes()
    except OSError as exc:
        logger.warning("Failed to read static photo path='%s': %s", photo_path, exc)
        return False

    boundary = f"----AvitoBotBoundary{uuid4().hex}"
    mime_type = mimetypes.guess_type(photo_path.name)[0] or "application/octet-stream"
    body_parts: list[bytes] = []

    def _append_field(name: str, value: str) -> None:
        body_parts.append(f"--{boundary}\r\n".encode("utf-8"))
        body_parts.append(f'Content-Disposition: form-data; name="{name}"\r\n\r\n'.encode("utf-8"))
        body_parts.append(value.encode("utf-8"))
        body_parts.append(b"\r\n")

    _append_field("chat_id", str(chat_id))
    _append_field("caption", caption)
    if reply_markup:
        _append_field("reply_markup", json.dumps(reply_markup, ensure_ascii=False))

    body_parts.append(f"--{boundary}\r\n".encode("utf-8"))
    body_parts.append(
        f'Content-Disposition: form-data; name="photo"; filename="{photo_path.name}"\r\n'.encode("utf-8")
    )
    body_parts.append(f"Content-Type: {mime_type}\r\n\r\n".encode("utf-8"))
    body_parts.append(photo_bytes)
    body_parts.append(b"\r\n")
    body_parts.append(f"--{boundary}--\r\n".encode("utf-8"))
    body = b"".join(body_parts)

    req = urllib_request.Request(
        f"https://api.telegram.org/bot{bot_token}/sendPhoto",
        data=body,
        headers={"Content-Type": f"multipart/form-data; boundary={boundary}"},
        method="POST",
    )
    try:
        with urllib_request.urlopen(req, timeout=15) as response:
            return 200 <= response.status < 300
    except Exception as exc:
        logger.warning("Failed to send telegram photo path='%s': %s", photo_path, exc)
        return False


def _send_telegram_photo_url(
    bot_token: str,
    chat_id: int,
    caption: str,
    photo_url: str,
    *,
    disable_web_page_preview: bool = True,
) -> bool:
    payload_data: dict[str, Any] = {
        "chat_id": chat_id,
        "photo": photo_url,
        "caption": caption,
        "disable_web_page_preview": disable_web_page_preview,
    }
    payload = json.dumps(payload_data).encode("utf-8")
    req = urllib_request.Request(
        f"https://api.telegram.org/bot{bot_token}/sendPhoto",
        data=payload,
        headers={"Content-Type": "application/json"},
        method="POST",
    )
    try:
        with urllib_request.urlopen(req, timeout=15) as response:
            return 200 <= response.status < 300
    except Exception as exc:
        logger.warning("Failed to send telegram photo url='%s': %s", photo_url, exc)
        return False


def broadcast_to_all_users(
    db: Session,
    text: str,
    photo_url: str | None = None,
) -> dict[str, int]:
    primary_bot = db.scalar(
        select(TelegramBot)
        .where(and_(TelegramBot.is_primary.is_(True), TelegramBot.is_active.is_(True)))
        .order_by(TelegramBot.id.asc())
    )
    if not primary_bot:
        primary_bot = db.scalar(
            select(TelegramBot).where(TelegramBot.is_active.is_(True)).order_by(TelegramBot.id.asc())
        )
    if not primary_bot:
        return {"total": 0, "sent": 0, "failed": 0}

    user_ids = [
        int(uid)
        for uid in db.scalars(select(User.telegram_id).order_by(User.id.asc())).all()
        if uid is not None
    ]

    sent = 0
    failed = 0
    for chat_id in user_ids:
        ok = False
        if photo_url:
            ok = _send_telegram_photo_url(primary_bot.bot_token, chat_id, text, photo_url)
        else:
            ok = _send_telegram_message(primary_bot.bot_token, chat_id, text)
        if ok:
            sent += 1
        else:
            failed += 1
    return {"total": len(user_ids), "sent": sent, "failed": failed}


def get_admin_notify_chat_ids(db: Session) -> list[int]:
    chat_ids: set[int] = set()

    for raw_id in str(settings.admin_notify_chat_ids or "").split(","):
        value = raw_id.strip()
        if not value or not re.fullmatch(r"-?\d+", value):
            continue
        chat_ids.add(int(value))

    for admin_telegram_id in db.scalars(select(User.telegram_id).where(User.is_admin.is_(True))).all():
        if admin_telegram_id:
            chat_ids.add(int(admin_telegram_id))

    return sorted(chat_ids)


def send_admin_event_message(db: Session, text: str) -> int:
    if not text or not text.strip():
        return 0

    primary_bot = db.scalar(
        select(TelegramBot)
        .where(and_(TelegramBot.is_primary.is_(True), TelegramBot.is_active.is_(True)))
        .order_by(TelegramBot.id.asc())
    )
    if not primary_bot:
        primary_bot = db.scalar(select(TelegramBot).where(TelegramBot.is_active.is_(True)).order_by(TelegramBot.id.asc()))
    if not primary_bot:
        return 0

    sent = 0
    for chat_id in get_admin_notify_chat_ids(db):
        if _send_telegram_message(primary_bot.bot_token, chat_id, text):
            sent += 1
    return sent


def _active_monitorings_count(db: Session) -> int:
    total = db.scalar(
        select(func.count(Monitoring.id)).where(
            and_(
                Monitoring.is_active.is_(True),
                Monitoring.link_configured.is_(True),
            )
        )
    )
    return int(total or 0)


def _usable_admin_proxies_count(db: Session) -> int:
    today = now_utc().date()
    total = db.scalar(
        select(func.count(ProxyConfig.id)).where(
            and_(
                ProxyConfig.is_active.is_(True),
                ProxyConfig.name.notlike("env-proxy-%"),
                or_(ProxyConfig.expires_on.is_(None), ProxyConfig.expires_on >= today),
            )
        )
    )
    return int(total or 0)


def proxy_capacity_status(db: Session) -> dict[str, int | bool]:
    active_monitorings = _active_monitorings_count(db)
    active_proxies = _usable_admin_proxies_count(db)
    required_proxies = active_monitorings * 2
    capacity_monitorings = active_proxies // 2
    missing_proxies = max(0, required_proxies - active_proxies)
    return {
        "active_monitorings": active_monitorings,
        "active_proxies": active_proxies,
        "required_proxies": required_proxies,
        "capacity_monitorings": capacity_monitorings,
        "missing_proxies": missing_proxies,
        "ok": missing_proxies == 0,
    }


def cleanup_expired_proxies(db: Session) -> int:
    today = now_utc().date()
    expired = db.scalars(
        select(ProxyConfig)
        .where(
            and_(
                ProxyConfig.name.notlike("env-proxy-%"),
                ProxyConfig.expires_on.is_not(None),
                ProxyConfig.expires_on < today,
            )
        )
        .order_by(ProxyConfig.expires_on.asc(), ProxyConfig.id.asc())
    ).all()
    if not expired:
        return 0

    deleted_rows = [
        {
            "name": proxy.name,
            "proxy_url": proxy.proxy_url,
            "expires_on": proxy.expires_on,
        }
        for proxy in expired
    ]
    for proxy in expired:
        db.delete(proxy)
    db.commit()

    preview = "\n".join(
        f"- {row['name']} ({row['expires_on'].strftime('%d.%m.%Y')})"
        for row in deleted_rows[:10]
        if row["expires_on"]
    )
    if len(deleted_rows) > 10:
        preview += f"\n...и еще {len(deleted_rows) - 10}"
    send_admin_event_message(
        db,
        (
            "Автоудалены истекшие прокси.\n"
            f"Удалено: {len(deleted_rows)}\n"
            f"{preview}\n\n"
            "Проверьте пул прокси и добавьте новые, если активных мониторингов больше, чем proxy_count // 2."
        ),
    )
    return len(deleted_rows)


def notify_proxy_capacity_if_needed(db: Session) -> bool:
    status = proxy_capacity_status(db)
    active_monitorings = int(status["active_monitorings"])
    active_proxies = int(status["active_proxies"])
    missing_proxies = int(status["missing_proxies"])
    if missing_proxies <= 0:
        setting = db.scalar(select(AppSetting).where(AppSetting.key == PROXY_CAPACITY_WARNING_SETTING_KEY))
        if setting and setting.value:
            setting.value = ""
            db.commit()
        return False

    signature = f"{active_monitorings}:{active_proxies}:{missing_proxies}"
    setting = db.scalar(select(AppSetting).where(AppSetting.key == PROXY_CAPACITY_WARNING_SETTING_KEY))
    if setting and setting.value == signature:
        return False

    sent = send_admin_event_message(
        db,
        (
            "Недостаточно прокси для активных мониторингов.\n"
            f"Активных мониторингов: {active_monitorings}\n"
            f"Активных прокси: {active_proxies}\n"
            f"Нужно минимум: {active_monitorings * 2}\n"
            f"Добавьте прокси: {missing_proxies}\n\n"
            "Правило: на 1 мониторинг должно быть 2 рабочих прокси."
        ),
    )
    if sent <= 0:
        return False

    if not setting:
        setting = AppSetting(key=PROXY_CAPACITY_WARNING_SETTING_KEY, value=signature)
        db.add(setting)
    else:
        setting.value = signature
    db.commit()
    return True


def notify_expiring_proxies(db: Session) -> int:
    today = now_utc().date()
    tomorrow = today + timedelta(days=1)
    candidates = db.scalars(
        select(ProxyConfig)
        .where(
            and_(
                ProxyConfig.is_active.is_(True),
                ProxyConfig.expires_on.is_not(None),
                ProxyConfig.expiry_notified_at.is_(None),
                ProxyConfig.expires_on <= tomorrow,
                ProxyConfig.expires_on >= today,
            )
        )
        .order_by(ProxyConfig.expires_on.asc(), ProxyConfig.id.asc())
    ).all()
    if not candidates:
        return 0

    notified = 0
    for proxy in candidates:
        if not proxy.expires_on:
            continue
        days_left = (proxy.expires_on - today).days
        expires_label = "завтра" if days_left == 1 else "сегодня"
        message = (
            "Прокси скоро истечет.\n"
            f"Название: {proxy.name}\n"
            f"Прокси: {proxy.proxy_url}\n"
            f"Действует до: {proxy.expires_on.strftime('%d.%m.%Y')} ({expires_label})"
        )
        if send_admin_event_message(db, message) > 0:
            proxy.expiry_notified_at = now_utc()
            notified += 1

    if notified:
        db.commit()
    return notified


def maintain_proxy_pool(db: Session) -> dict[str, int | bool]:
    deleted_expired = cleanup_expired_proxies(db)
    expiring_notified = notify_expiring_proxies(db)
    capacity_notified = notify_proxy_capacity_if_needed(db)
    status = proxy_capacity_status(db)
    return {
        **status,
        "deleted_expired": deleted_expired,
        "expiring_notified": expiring_notified,
        "capacity_notified": capacity_notified,
    }


def _format_message_datetime(value: datetime | None) -> str | None:
    if not value:
        return None
    normalized = value if value.tzinfo else value.replace(tzinfo=timezone.utc)
    moscow_time = normalized.astimezone(timezone(timedelta(hours=3)))
    return moscow_time.strftime("%d.%m.%Y %H:%M МСК")


def send_subscription_assigned_bot_message(
    db: Session,
    user: User,
    *,
    plan: TariffPlan | None = None,
    subscription: UserSubscription | None = None,
    intro: str | None = None,
) -> bool:
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
        .order_by(Monitoring.id.desc())
    )
    if not assigned_bot and not plan and not subscription and not intro:
        return False

    lines: list[str] = []
    if intro:
        lines.append(intro.strip())
    elif plan:
        lines.append("Ваша подписка активирована.")

    if plan:
        lines.append(f"Тариф: {plan.name}")
    if subscription and subscription.ends_at:
        formatted_ends_at = _format_message_datetime(subscription.ends_at)
        if formatted_ends_at:
            lines.append(f"Действует до: {formatted_ends_at}")

    reply_markup = None
    if assigned_bot:
        if assigned_bot.bot_username:
            nickname = f"@{assigned_bot.bot_username.lstrip('@')}"
        else:
            nickname = assigned_bot.name or "бот"
        lines.append(f"Назначенный бот: {nickname}")
        bot_link = _build_bot_link(assigned_bot.bot_username)
        if bot_link:
            lines.append("Откройте назначенного бота и запустите его, чтобы получать уведомления.")
            reply_markup = {
                "inline_keyboard": [
                    [
                        {
                            "text": "Открыть назначенного бота",
                            "url": bot_link,
                        }
                    ]
                ]
            }
        else:
            lines.append("Откройте назначенного бота и запустите его, чтобы получать уведомления.")
    else:
        lines.append("Бот пока не назначен. Администратор должен добавить доступного бота.")

    return _send_telegram_message(primary_bot.bot_token, user.telegram_id, "\n".join(lines), reply_markup=reply_markup)


def _build_bot_link(bot_username: str | None) -> str | None:
    username = str(bot_username or "").strip().lstrip("@")
    if not username:
        return None
    return f"https://t.me/{username}"


def build_subscription_purchase_url(db: Session) -> str | None:
    primary_bot = db.scalar(
        select(TelegramBot)
        .where(
            and_(
                TelegramBot.is_primary.is_(True),
                TelegramBot.is_active.is_(True),
                TelegramBot.bot_username.is_not(None),
            )
        )
        .order_by(TelegramBot.id.asc())
    )
    if primary_bot:
        base = _build_bot_link(primary_bot.bot_username)
        if base:
            separator = "&" if "?" in base else "?"
            return f"{base}{separator}start=subscription"

    fallback_bot = db.scalar(
        select(TelegramBot)
        .where(
            and_(
                TelegramBot.is_active.is_(True),
                TelegramBot.bot_username.is_not(None),
            )
        )
        .order_by(TelegramBot.id.asc())
    )
    if fallback_bot:
        base = _build_bot_link(fallback_bot.bot_username)
        if base:
            separator = "&" if "?" in base else "?"
            return f"{base}{separator}start=subscription"

    fallback_url = str(settings.miniapp_public_url or "").strip()
    return fallback_url or None


def build_subscription_cta_markup(db: Session, button_text: str = "Оформить подписку") -> dict[str, Any] | None:
    target_url = build_subscription_purchase_url(db)
    if not target_url:
        return None
    caption = str(button_text or "").strip() or "Оформить подписку"
    return {
        "inline_keyboard": [
            [
                {
                    "text": caption,
                    "url": target_url,
                }
            ]
        ]
    }


def send_monitoring_bot_message(
    db: Session,
    monitoring: Monitoring,
    telegram_id: int,
    text: str,
    *,
    reply_markup: dict[str, Any] | None = None,
    photo_key: str | None = None,
) -> bool:
    if not monitoring.bot_id or not text or not text.strip():
        return False

    bot = monitoring.bot if monitoring.bot and monitoring.bot.id == monitoring.bot_id else None
    if not bot:
        bot = db.get(TelegramBot, monitoring.bot_id)
    if not bot or not bot.bot_token:
        return False

    photo_path = _resolve_static_photo_path(photo_key)
    if photo_path and _send_telegram_photo(
        bot.bot_token,
        telegram_id,
        text,
        photo_path,
        reply_markup=reply_markup,
    ):
        return True

    return _send_telegram_message(
        bot.bot_token,
        telegram_id,
        text,
        reply_markup=reply_markup,
    )


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


def _format_price_line(price_rub: int | None) -> str:
    return f"{price_rub:,} ₽".replace(",", " ") if price_rub is not None else "Цена не указана"


def _cleanup_text(value: str | None, max_len: int) -> str | None:
    if not value:
        return None
    normalized = " ".join(str(value).split())
    normalized = normalized.replace("<", "‹").replace(">", "›")
    if not normalized:
        return None
    if len(normalized) <= max_len:
        return normalized
    return f"{normalized[: max_len - 1]}…"


def extract_item_description(raw_json: dict[str, Any] | None) -> str | None:
    if not isinstance(raw_json, dict):
        return None
    return _cleanup_text(raw_json.get("description"), 520)


def _normalize_media_url(value: Any) -> str | None:
    if not isinstance(value, str):
        return None

    raw = value.strip()
    if not raw:
        return None

    if raw.startswith("//"):
        return f"https:{raw}"
    if raw.startswith("/"):
        return f"https://www.avito.ru{raw}"
    if raw.startswith(("http://", "https://")):
        return raw
    return None


def _pick_first_url(value: Any) -> str | None:
    normalized = _normalize_media_url(value)
    if normalized:
        return normalized
    if isinstance(value, dict):
        for nested in value.values():
            found = _pick_first_url(nested)
            if found:
                return found
    if isinstance(value, list):
        for nested in value:
            found = _pick_first_url(nested)
            if found:
                return found
    return None


def extract_item_photo_url(raw_json: dict[str, Any] | None) -> str | None:
    if not isinstance(raw_json, dict):
        return None

    gallery = raw_json.get("gallery")
    if isinstance(gallery, dict):
        for key in ("imageLargeUrl", "imageUrl", "imageVipUrl", "imageLargeVipUrl"):
            found = _pick_first_url(gallery.get(key))
            if found:
                return found

    images = raw_json.get("images")
    found_from_images = _pick_first_url(images)
    if found_from_images:
        return found_from_images

    for key in ("phoneImage", "imageUrl", "mainImage", "coverImage", "previewImage"):
        found = _pick_first_url(raw_json.get(key))
        if found:
            return found

    for nested_key in ("gallery", "images", "photo", "photos", "image", "picture", "media"):
        found = _pick_first_url(raw_json.get(nested_key))
        if found:
            return found

    return None


def _build_optional_description_block(description: str | None) -> str:
    if not description:
        return ""
    cleaned = " ".join(str(description).split())
    cleaned = cleaned.replace("<", "‹").replace(">", "›")
    if not cleaned:
        return ""
    return f"\n<blockquote expandable>{html.escape(cleaned)}</blockquote>"


def _ru_plural(count: int, one: str, few: str, many: str) -> str:
    value = abs(count) % 100
    if 11 <= value <= 14:
        return many
    last = value % 10
    if last == 1:
        return one
    if 2 <= last <= 4:
        return few
    return many


def _try_int(value: Any) -> int | None:
    if isinstance(value, bool):
        return None
    if isinstance(value, int):
        return value
    if isinstance(value, float):
        return int(value)
    if not isinstance(value, str):
        return None
    digits = "".join(ch for ch in value if ch.isdigit())
    if not digits:
        return None
    try:
        return int(digits)
    except ValueError:
        return None


def _try_float(value: Any) -> float | None:
    if isinstance(value, bool):
        return None
    if isinstance(value, (int, float)):
        return float(value)
    if not isinstance(value, str):
        return None
    cleaned = value.strip().replace(",", ".")
    numeric = "".join(ch for ch in cleaned if ch.isdigit() or ch == ".")
    if not numeric:
        return None
    try:
        return float(numeric)
    except ValueError:
        return None


def _iter_key_values(data: Any):
    if isinstance(data, dict):
        for key, value in data.items():
            yield str(key), value
            yield from _iter_key_values(value)
    elif isinstance(data, list):
        for item in data:
            yield from _iter_key_values(item)


def _first_by_key(raw_json: dict[str, Any] | None, key_parts: tuple[str, ...], parser) -> Any:
    if not isinstance(raw_json, dict):
        return None
    for key, value in _iter_key_values(raw_json):
        key_lower = key.lower()
        if not any(part in key_lower for part in key_parts):
            continue
        parsed = parser(value)
        if parsed is not None:
            return parsed
    return None


def extract_seller_stats_block(raw_json: dict[str, Any] | None) -> str:
    if not isinstance(raw_json, dict):
        return ""

    rating = _first_by_key(raw_json, ("rating", "score", "stars"), _try_float)
    reviews_count = _first_by_key(raw_json, ("review", "feedback"), _try_int)

    lines: list[str] = []
    if rating is not None:
        lines.append(f"⭐️ {rating:.1f}")
    if reviews_count is not None:
        noun = _ru_plural(reviews_count, "отзыв", "отзыва", "отзывов")
        lines.append(f"{reviews_count} {noun}")

    if not lines:
        return ""
    return "\n".join(lines)


def _build_optional_seller_stats_block(raw_json: dict[str, Any] | None) -> str:
    block = extract_seller_stats_block(raw_json)
    if not block:
        return ""
    return f"\n\n{html.escape(block)}"


def _ensure_s104_query_param(url: str) -> str:
    raw = (url or "").strip()
    if not raw:
        return raw

    try:
        parsed = urlsplit(raw)
    except Exception:
        return raw

    query = parsed.query or ""
    if re.search(r"(^|&)s=", query):
        return raw

    new_query = f"{query}&s=104" if query else "s=104"
    return urlunsplit((parsed.scheme, parsed.netloc, parsed.path, new_query, parsed.fragment))


def _build_short_avito_url(url: str, avito_ad_id: str | None = None) -> str:
    if avito_ad_id:
        cleaned_id = "".join(ch for ch in str(avito_ad_id) if ch.isdigit())
        if cleaned_id:
            return _ensure_s104_query_param(f"https://www.avito.ru/{cleaned_id}")

    parsed = urlsplit(url or "")
    path = (parsed.path or "").rstrip("/")
    if path:
        slug_match = re.search(r"(\d{5,})$", path)
        if slug_match:
            return _ensure_s104_query_param(f"https://www.avito.ru/{slug_match.group(1)}")

        direct_match = re.fullmatch(r"/?(\d{5,})", path)
        if direct_match:
            return _ensure_s104_query_param(f"https://www.avito.ru/{direct_match.group(1)}")

    return _ensure_s104_query_param(url)


def _format_published_at_line(published_at: datetime | None) -> str:
    if not published_at:
        return "Время публикации не указано"
    try:
        if published_at.tzinfo is None:
            return published_at.strftime("%d.%m.%Y %H:%M:%S")
        return published_at.astimezone(timezone(timedelta(hours=3))).strftime("%d.%m.%Y %H:%M:%S")
    except Exception:
        return str(published_at)


def _build_published_at_block(published_at: datetime | None) -> str:
    return f"\n\n🕒 {html.escape(_format_published_at_line(published_at))}"


def format_new_item_message(
    title: str,
    price_rub: int | None,
    url: str,
    location: str | None,
    published_at: datetime | None = None,
    avito_ad_id: str | None = None,
    description: str | None = None,
    raw_json: dict[str, Any] | None = None,
    include_description: bool = True,
    include_seller_info: bool = True,
) -> str:
    price_line = html.escape(_format_price_line(price_rub))
    location_line = html.escape(location or "Локация не указана")
    title_line = html.escape(_cleanup_text(title, 160) or "Без названия")
    item_url = html.escape(_build_short_avito_url(url, avito_ad_id))
    return (
        f"<b>{title_line}</b>\n"
        f"💰 {price_line}\n"
        f"📍 {location_line}\n"
        f"🔗 {item_url}"
        f"{_build_optional_description_block(description) if include_description else ''}"
        f"{_build_optional_seller_stats_block(raw_json) if include_seller_info else ''}"
        f"{_build_published_at_block(published_at)}"
    )


def format_price_change_message(
    title: str,
    old_price_rub: int | None,
    new_price_rub: int | None,
    url: str,
    location: str | None,
    published_at: datetime | None = None,
    avito_ad_id: str | None = None,
    description: str | None = None,
    raw_json: dict[str, Any] | None = None,
    include_description: bool = True,
    include_seller_info: bool = True,
) -> str:
    old_line = html.escape(_format_price_line(old_price_rub))
    new_line = html.escape(_format_price_line(new_price_rub))
    location_line = html.escape(location or "Локация не указана")
    title_line = html.escape(_cleanup_text(title, 160) or "Без названия")
    item_url = html.escape(_build_short_avito_url(url, avito_ad_id))
    return (
        "❗️❗️ 💸 Изменение стоимости ❗️❗️\n"
        f"<b>{title_line}</b>\n"
        f"⬇️ Было: {old_line}\n"
        f"💰 Стало: {new_line}\n"
        f"📍 {location_line}\n"
        f"🔗 {item_url}"
        f"{_build_optional_description_block(description) if include_description else ''}"
        f"{_build_optional_seller_stats_block(raw_json) if include_seller_info else ''}"
        f"{_build_published_at_block(published_at)}"
    )


def add_days(base: datetime, days: int) -> datetime:
    return base + timedelta(days=days)
