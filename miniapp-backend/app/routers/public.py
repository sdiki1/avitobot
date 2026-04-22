from datetime import datetime
from urllib.parse import parse_qsl, urlencode, urlsplit, urlunsplit

from fastapi import APIRouter, Depends, HTTPException, Query, Response, status
from sqlalchemy import and_, desc, func, select, update
from sqlalchemy.orm import Session

from app.config import settings
from app.database import get_db
from app.models import Monitoring, MonitoringItem, Notification, Payment, TariffPlan, TelegramBot, User, UserSubscription
from app.schemas import (
    BotReference,
    MiniAppContentResponse,
    MiniAppSignInRequest,
    MonitoringCreate,
    MonitoringUpdate,
    MonitoringItemResponse,
    MonitoringPurchaseRequest,
    MonitoringResponse,
    NotificationResponse,
    OnboardingTrialRequest,
    OnboardingTrialResponse,
    PurchaseSubscriptionRequest,
    PurchaseSubscriptionResponse,
    TariffPlanResponse,
    TelegramAuthRequest,
    TelegramAuthResolveResponse,
    UserResponse,
)
from app.services.helpers import (
    activate_user_subscription,
    apply_referral_code,
    ensure_subscription_monitoring_slots,
    ensure_user_referral_code,
    get_miniapp_content_settings,
    get_active_subscription_query,
    get_available_bot_for_user,
    get_or_create_user,
    normalize_monitoring_url,
    now_utc,
    parse_miniapp_auth_token,
    reward_referrer_for_payment,
    send_admin_event_message,
    send_monitoring_bot_message,
    send_subscription_assigned_bot_message,
)
from app.services.notification_queue import purge_monitoring_notifications
from app.services.yookassa import YooKassaError, create_sbp_payment, get_payment as get_yookassa_payment, yookassa_is_configured
from app.services.miniapp_auth import (
    assert_telegram_id_match,
    clear_miniapp_session,
    get_active_bot_tokens,
    issue_miniapp_session,
    parse_and_validate_init_data,
    require_miniapp_user,
)

router = APIRouter(prefix="/public", tags=["public"])
webhook_router = APIRouter(tags=["webhooks"])
ONBOARDING_TRIAL_DAYS = 1


def _build_bot_link(username: str | None) -> str | None:
    if not username:
        return None
    return f"https://t.me/{username.lstrip('@')}"


def _to_bot_ref(bot: TelegramBot | None) -> BotReference | None:
    if not bot:
        return None
    return BotReference(
        id=bot.id,
        name=bot.name,
        bot_username=bot.bot_username,
        bot_link=_build_bot_link(bot.bot_username),
    )


def _monitoring_to_schema(mon: Monitoring) -> MonitoringResponse:
    return MonitoringResponse(
        id=mon.id,
        url=normalize_monitoring_url(mon.url),
        title=mon.title,
        keywords_white=[x for x in (mon.keywords_white or "").split(",") if x],
        keywords_black=[x for x in (mon.keywords_black or "").split(",") if x],
        min_price=mon.min_price,
        max_price=mon.max_price,
        geo=mon.geo,
        is_active=mon.is_active,
        link_configured=mon.link_configured,
        include_photo=mon.include_photo,
        include_description=mon.include_description,
        include_seller_info=mon.include_seller_info,
        notify_price_drop=mon.notify_price_drop,
        last_checked_at=mon.last_checked_at,
        bot=_to_bot_ref(mon.bot),
    )


def _miniapp_content_response(values: dict[str, str]) -> MiniAppContentResponse:
    return MiniAppContentResponse(
        support_title=values["miniapp_info_support_title"],
        support_url=values["miniapp_info_support_url"],
        faq_title=values["miniapp_info_faq_title"],
        faq_url=values["miniapp_info_faq_url"],
        news_title=values["miniapp_info_news_title"],
        news_url=values["miniapp_info_news_url"],
        terms_title=values["miniapp_info_terms_title"],
        terms_url=values["miniapp_info_terms_url"],
        privacy_title=values["miniapp_info_privacy_title"],
        privacy_url=values["miniapp_info_privacy_url"],
        subscriptions_title=values["miniapp_subscriptions_title"],
        subscriptions_hint=values["miniapp_subscriptions_hint"],
        profile_title=values["miniapp_profile_title"],
        info_links=[
            {"key": "support", "title": values["miniapp_info_support_title"], "url": values["miniapp_info_support_url"]},
            {"key": "faq", "title": values["miniapp_info_faq_title"], "url": values["miniapp_info_faq_url"]},
            {"key": "news", "title": values["miniapp_info_news_title"], "url": values["miniapp_info_news_url"]},
            {"key": "terms", "title": values["miniapp_info_terms_title"], "url": values["miniapp_info_terms_url"]},
            {"key": "privacy", "title": values["miniapp_info_privacy_title"], "url": values["miniapp_info_privacy_url"]},
        ],
    )


def _require_active_subscription(db: Session, user_id: int) -> UserSubscription:
    active_sub = db.scalar(get_active_subscription_query(user_id))
    if not active_sub:
        raise HTTPException(
            status_code=status.HTTP_402_PAYMENT_REQUIRED,
            detail="Нет активной подписки. Выберите тариф в miniapp.",
        )
    return active_sub


def _require_slot_available(db: Session, user_id: int, links_limit: int) -> int:
    total_links = db.scalar(select(func.count(Monitoring.id)).where(Monitoring.user_id == user_id)) or 0
    if total_links >= links_limit:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"Лимит мониторингов по тарифу исчерпан ({links_limit})",
        )
    return total_links


def _require_free_bots_for_new_slots(db: Session, user_id: int, slots_to_add: int) -> None:
    if slots_to_add <= 0:
        return

    total_active_monitoring_bots = db.scalar(
        select(func.count(TelegramBot.id)).where(
            and_(
                TelegramBot.is_active.is_(True),
                TelegramBot.is_primary.is_(False),
            )
        )
    ) or 0
    used_by_user = db.scalar(
        select(func.count(func.distinct(Monitoring.bot_id))).where(
            and_(
                Monitoring.user_id == user_id,
                Monitoring.bot_id.is_not(None),
            )
        )
    ) or 0
    free_bots = max(0, int(total_active_monitoring_bots) - int(used_by_user))
    if free_bots < slots_to_add:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=(
                "Недостаточно свободных ботов для новой подписки. "
                f"Нужно: {slots_to_add}, доступно: {free_bots}. Добавьте ботов в админке."
            ),
        )


def _activate_onboarding_trial(db: Session, user: User) -> UserSubscription | None:
    existing_subscriptions = db.scalar(select(func.count(UserSubscription.id)).where(UserSubscription.user_id == user.id)) or 0
    if existing_subscriptions > 0:
        return None

    plan = db.scalar(
        select(TariffPlan)
        .where(and_(TariffPlan.is_active.is_(True), TariffPlan.links_limit > 0))
        .order_by(TariffPlan.links_limit.asc(), TariffPlan.price_rub.asc(), TariffPlan.id.asc())
    )
    if not plan:
        return None

    db.add(
        Payment(
            user_id=user.id,
            plan_id=plan.id,
            amount_rub=0,
            status="completed",
            provider="trial_manual",
        )
    )
    subscription = activate_user_subscription(
        db,
        user.id,
        plan,
        duration_days_override=ONBOARDING_TRIAL_DAYS,
        amount_paid_override=0,
        is_trial=True,
    )
    current_total_slots = db.scalar(select(func.count(Monitoring.id)).where(Monitoring.user_id == user.id)) or 0
    ensure_subscription_monitoring_slots(db, user.id, current_total_slots + 1)
    send_subscription_assigned_bot_message(db, user)
    send_admin_event_message(
        db,
        (
            "🧪 Активирован пробный период\n"
            f"Пользователь: {user.telegram_id}\n"
            f"Срок: {ONBOARDING_TRIAL_DAYS} дн."
        ),
    )
    return subscription


def _safe_int(value: object, default: int = 0) -> int:
    try:
        return int(value)
    except (TypeError, ValueError):
        return default


def _append_query_param(url: str, key: str, value: str) -> str:
    raw = (url or "").strip()
    if not raw:
        return raw
    parsed = urlsplit(raw)
    query = dict(parse_qsl(parsed.query, keep_blank_values=True))
    query[key] = value
    return urlunsplit((parsed.scheme, parsed.netloc, parsed.path, urlencode(query), parsed.fragment))


def _parse_iso_datetime(value: object) -> datetime | None:
    if isinstance(value, datetime):
        return value
    if not isinstance(value, str):
        return None
    raw = value.strip()
    if not raw:
        return None
    try:
        return datetime.fromisoformat(raw.replace("Z", "+00:00"))
    except ValueError:
        return None


def _payment_payload(payment: Payment) -> dict:
    payload = payment.payload if isinstance(payment.payload, dict) else {}
    return dict(payload)


def _refund_referral_if_needed(user: User, payload: dict) -> dict:
    referral_used = max(0, _safe_int(payload.get("referral_used_rub"), 0))
    if referral_used <= 0:
        return payload
    if bool(payload.get("referral_refunded")):
        return payload
    user.referral_balance_rub = max(0, int(user.referral_balance_rub or 0)) + referral_used
    payload["referral_refunded"] = True
    return payload


def _build_purchase_response(
    *,
    ok: bool,
    user_id: int,
    plan_id: int,
    amount_rub: int,
    referral_used_rub: int,
    total_price_rub: int,
    subscription: UserSubscription | None = None,
    payment: Payment | None = None,
    requires_payment: bool = False,
    payment_status: str | None = None,
    payment_url: str | None = None,
    message: str | None = None,
) -> PurchaseSubscriptionResponse:
    payload = _payment_payload(payment) if payment else {}
    sub_id = subscription.id if subscription else (_safe_int(payload.get("subscription_id"), 0) or None)
    ends_at = subscription.ends_at if subscription else _parse_iso_datetime(payload.get("ends_at"))
    status_value = payment_status or str(payload.get("yookassa_status") or (payment.status if payment else "") or "").strip() or None
    confirmation_url = payment_url or (str(payload.get("confirmation_url") or "").strip() or None)
    return PurchaseSubscriptionResponse(
        ok=ok,
        requires_payment=requires_payment,
        payment_id=payment.id if payment else None,
        payment_status=status_value,
        payment_url=confirmation_url,
        subscription_id=sub_id,
        user_id=user_id,
        plan_id=plan_id,
        ends_at=ends_at,
        is_trial=False,
        amount_rub=max(0, int(amount_rub)),
        referral_used_rub=max(0, int(referral_used_rub)),
        total_price_rub=max(0, int(total_price_rub)),
        message=message,
    )


def _apply_monitoring_purchase_payload(db: Session, user: User, payload: dict, target_total_slots: int) -> None:
    ensure_subscription_monitoring_slots(db, user.id, target_total_slots)

    monitoring_id = _safe_int(payload.get("monitoring_id"), 0)
    target_monitoring = None
    if monitoring_id > 0:
        target_monitoring = db.scalar(
            select(Monitoring).where(and_(Monitoring.id == monitoring_id, Monitoring.user_id == user.id))
        )

    configured_monitoring = target_monitoring
    if not configured_monitoring:
        configured_monitoring = db.scalar(
            select(Monitoring)
            .where(
                and_(
                    Monitoring.user_id == user.id,
                    Monitoring.link_configured.is_(False),
                )
            )
            .order_by(Monitoring.id.desc())
        )
    if not configured_monitoring:
        return

    monitoring_title = str(payload.get("monitoring_title") or "").strip()
    if monitoring_title:
        configured_monitoring.title = monitoring_title

    monitoring_url_raw = payload.get("monitoring_url")
    if monitoring_url_raw is not None:
        cleaned_url = normalize_monitoring_url(str(monitoring_url_raw))
        if cleaned_url:
            configured_monitoring.url = cleaned_url
            configured_monitoring.link_configured = True


def _finalize_subscription_payment(
    *,
    db: Session,
    user: User,
    plan: TariffPlan,
    payment: Payment,
) -> UserSubscription:
    payload = _payment_payload(payment)
    existing_subscription_id = _safe_int(payload.get("subscription_id"), 0)
    if bool(payload.get("finalized")) and existing_subscription_id > 0:
        existing = db.get(UserSubscription, existing_subscription_id)
        if existing:
            return existing

    amount_to_pay = max(0, _safe_int(payment.amount_rub, 0))
    referral_used = max(0, _safe_int(payload.get("referral_used_rub"), 0))
    total_price = max(amount_to_pay + referral_used, _safe_int(payload.get("total_price_rub"), amount_to_pay + referral_used))
    current_total_slots = db.scalar(select(func.count(Monitoring.id)).where(Monitoring.user_id == user.id)) or 0
    target_total_slots = max(
        int(current_total_slots),
        _safe_int(payload.get("target_total_slots"), int(current_total_slots)),
    )

    subscription = activate_user_subscription(
        db,
        user.id,
        plan,
        amount_paid_override=amount_to_pay,
        is_trial=False,
    )
    _apply_monitoring_purchase_payload(db, user, payload, target_total_slots)

    reward = reward_referrer_for_payment(db, user, amount_to_pay)
    payment.status = "completed"
    payload["finalized"] = True
    payload["subscription_id"] = subscription.id
    payload["ends_at"] = subscription.ends_at.isoformat()
    payload["reward_rub"] = reward
    payload["paid_amount_rub"] = amount_to_pay
    payload["referral_used_rub"] = referral_used
    payload["total_price_rub"] = total_price
    payment.payload = payload
    db.commit()

    send_subscription_assigned_bot_message(db, user)
    send_admin_event_message(
        db,
        (
            "💳 Покупка подписки\n"
            f"Пользователь: {user.telegram_id}\n"
            f"Тариф: {plan.name}\n"
            f"Сумма: {amount_to_pay} ₽\n"
            f"Списано с реф. баланса: {referral_used} ₽\n"
            f"Начислено рефереру: {reward} ₽"
        ),
    )
    return subscription


@router.post("/auth/telegram", response_model=UserResponse)
def telegram_auth(payload: TelegramAuthRequest, db: Session = Depends(get_db)) -> User:
    existed_before = db.scalar(select(User.id).where(User.telegram_id == payload.telegram_id)) is not None
    user = get_or_create_user(
        db,
        telegram_id=payload.telegram_id,
        username=payload.username,
        full_name=payload.full_name,
    )
    apply_referral_code(db, user, payload.referral_code)
    user = ensure_user_referral_code(db, user)
    if not existed_before:
        username_line = f"@{user.username}" if user.username else "—"
        send_admin_event_message(
            db,
            (
                "👤 Новый пользователь в боте\n"
                f"Telegram ID: {user.telegram_id}\n"
                f"Username: {username_line}"
            ),
        )
    return user


@router.post("/auth/miniapp/signin", response_model=TelegramAuthResolveResponse)
def miniapp_signin(
    payload: MiniAppSignInRequest,
    response: Response,
    db: Session = Depends(get_db),
) -> TelegramAuthResolveResponse:
    identity = parse_and_validate_init_data(payload.init_data, get_active_bot_tokens(db))
    user = get_or_create_user(
        db,
        telegram_id=identity.telegram_id,
        username=identity.username,
        full_name=identity.full_name,
    )
    user = ensure_user_referral_code(db, user)
    issue_miniapp_session(response, user.telegram_id)
    return TelegramAuthResolveResponse(
        telegram_id=user.telegram_id,
        user=UserResponse.model_validate(user),
    )


@router.get("/auth/session", response_model=TelegramAuthResolveResponse)
def miniapp_session(auth_user: User = Depends(require_miniapp_user)) -> TelegramAuthResolveResponse:
    return TelegramAuthResolveResponse(
        telegram_id=auth_user.telegram_id,
        user=UserResponse.model_validate(auth_user),
    )


@router.post("/auth/logout")
def miniapp_logout(response: Response) -> dict[str, bool]:
    clear_miniapp_session(response)
    return {"ok": True}


@router.get("/auth/resolve", response_model=TelegramAuthResolveResponse)
def resolve_auth(
    response: Response,
    auth: str = Query(...),
    db: Session = Depends(get_db),
) -> TelegramAuthResolveResponse:
    telegram_id = parse_miniapp_auth_token(auth)
    if telegram_id is None:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Invalid auth token")
    user = get_or_create_user(db, telegram_id=telegram_id, username=None, full_name=None)
    user = ensure_user_referral_code(db, user)
    issue_miniapp_session(response, user.telegram_id)
    return TelegramAuthResolveResponse(
        telegram_id=telegram_id,
        user=UserResponse.model_validate(user),
    )


@router.post("/onboarding-trial", response_model=OnboardingTrialResponse)
def onboarding_trial(
    payload: OnboardingTrialRequest,
    auth_user: User = Depends(require_miniapp_user),
    db: Session = Depends(get_db),
) -> OnboardingTrialResponse:
    assert_telegram_id_match(auth_user, payload.telegram_id)
    user = ensure_user_referral_code(db, auth_user)
    subscription = _activate_onboarding_trial(db, user)
    if not subscription:
        return OnboardingTrialResponse(granted=False, days=ONBOARDING_TRIAL_DAYS, ends_at=None)
    return OnboardingTrialResponse(granted=True, days=ONBOARDING_TRIAL_DAYS, ends_at=subscription.ends_at)


@router.get("/plans", response_model=list[TariffPlanResponse])
def list_plans(db: Session = Depends(get_db)) -> list[TariffPlan]:
    return list(
        db.scalars(
            select(TariffPlan)
            .where(TariffPlan.is_active.is_(True))
            .order_by(
                TariffPlan.plan_format.asc(),
                TariffPlan.duration_days.asc(),
                TariffPlan.price_rub.asc(),
                TariffPlan.id.asc(),
            )
        )
    )


@router.get("/miniapp-content", response_model=MiniAppContentResponse)
def miniapp_content(db: Session = Depends(get_db)) -> MiniAppContentResponse:
    values = get_miniapp_content_settings(db)
    return _miniapp_content_response(values)


@router.get("/profile")
def profile(
    telegram_id: int = Query(...),
    auth_user: User = Depends(require_miniapp_user),
    db: Session = Depends(get_db),
) -> dict:
    assert_telegram_id_match(auth_user, telegram_id)
    user = ensure_user_referral_code(db, auth_user)
    subscription = db.scalar(get_active_subscription_query(user.id))
    subscriptions = db.scalars(
        select(UserSubscription)
        .where(UserSubscription.user_id == user.id)
        .order_by(UserSubscription.created_at.desc())
        .limit(50)
    ).all()
    monitorings_total = db.scalar(select(func.count(Monitoring.id)).where(Monitoring.user_id == user.id))
    active_monitorings = db.scalar(
        select(func.count(Monitoring.id)).where(and_(Monitoring.user_id == user.id, Monitoring.is_active.is_(True)))
    )
    user_monitorings = db.scalars(
        select(Monitoring).where(Monitoring.user_id == user.id).order_by(Monitoring.id.asc())
    ).all()
    referral_bot = db.scalar(
        select(TelegramBot)
        .where(
            and_(
                TelegramBot.is_active.is_(True),
                TelegramBot.bot_username.is_not(None),
                TelegramBot.is_primary.is_(True),
            )
        )
        .order_by(TelegramBot.id.asc())
    )
    if not referral_bot:
        referral_bot = db.scalar(
            select(TelegramBot)
            .where(and_(TelegramBot.is_active.is_(True), TelegramBot.bot_username.is_not(None)))
            .order_by(TelegramBot.id.asc())
        )
    referral_link = None
    if referral_bot and user.referral_code:
        base = _build_bot_link(referral_bot.bot_username)
        if base:
            referral_link = f"{base}?start={user.referral_code}"

    payload = {
        "user": UserResponse.model_validate(user),
        "active_monitorings": active_monitorings or 0,
        "total_monitorings": monitorings_total or 0,
        "referral_link": referral_link,
        "subscription": None,
        "subscriptions": [],
        "can_activate_trial": len(subscriptions) == 0,
        "assigned_bots": [],
    }
    if subscription:
        payload["subscription"] = {
            "id": subscription.id,
            "plan_id": subscription.plan_id,
            "ends_at": subscription.ends_at,
            "status": subscription.status,
            "is_trial": subscription.is_trial,
            "links_limit": subscription.plan.links_limit if subscription.plan else 0,
            "plan_name": subscription.plan.name if subscription.plan else "Без тарифа",
        }

    payload["subscriptions"] = [
        {
            "id": sub.id,
            "plan_id": sub.plan_id,
            "plan_name": sub.plan.name if sub.plan else "Без тарифа",
            "status": sub.status,
            "is_trial": sub.is_trial,
            "amount_paid": sub.amount_paid,
            "links_limit": sub.plan.links_limit if sub.plan else 0,
            "started_at": sub.started_at,
            "ends_at": sub.ends_at,
            "created_at": sub.created_at,
        }
        for sub in subscriptions
    ]

    bots: dict[int, dict] = {}
    for mon in user_monitorings:
        if not mon.bot:
            continue
        if mon.bot.id in bots:
            continue
        bots[mon.bot.id] = {
            "id": mon.bot.id,
            "name": mon.bot.name,
            "bot_username": mon.bot.bot_username,
            "bot_link": _build_bot_link(mon.bot.bot_username),
        }
    payload["assigned_bots"] = list(bots.values())
    return payload


@router.get("/monitorings", response_model=list[MonitoringResponse])
def list_monitorings(
    telegram_id: int = Query(...),
    auth_user: User = Depends(require_miniapp_user),
    db: Session = Depends(get_db),
) -> list[MonitoringResponse]:
    assert_telegram_id_match(auth_user, telegram_id)
    user = auth_user
    monitorings = db.scalars(select(Monitoring).where(Monitoring.user_id == user.id).order_by(Monitoring.id.desc())).all()
    return [_monitoring_to_schema(m) for m in monitorings]


@router.post("/monitorings", response_model=MonitoringResponse)
def create_monitoring(
    payload: MonitoringCreate,
    auth_user: User = Depends(require_miniapp_user),
    db: Session = Depends(get_db),
) -> MonitoringResponse:
    assert_telegram_id_match(auth_user, payload.telegram_id)
    user = auth_user
    active_sub = _require_active_subscription(db, user.id)
    links_limit = active_sub.plan.links_limit if active_sub.plan else 0
    _require_slot_available(db, user.id, links_limit)
    bot = get_available_bot_for_user(db, user.id)
    if not bot:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="Нет доступного бота для нового мониторинга. Добавьте ботов в админке.",
        )
    if not payload.url or not payload.url.strip():
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="URL обязателен")

    normalized_url = normalize_monitoring_url(payload.url)

    monitoring = Monitoring(
        user_id=user.id,
        bot_id=bot.id,
        url=normalized_url,
        title=payload.title,
        keywords_white=",".join(payload.keywords_white),
        keywords_black=",".join(payload.keywords_black),
        min_price=payload.min_price,
        max_price=payload.max_price,
        geo=payload.geo,
        is_active=True,
        link_configured=True,
        include_photo=payload.include_photo,
        include_description=payload.include_description,
        include_seller_info=payload.include_seller_info,
        notify_price_drop=payload.notify_price_drop,
    )
    db.add(monitoring)
    db.commit()
    db.refresh(monitoring)
    return _monitoring_to_schema(monitoring)


@router.patch("/monitorings/{monitoring_id}", response_model=MonitoringResponse)
def update_monitoring(
    monitoring_id: int,
    payload: MonitoringUpdate,
    auth_user: User = Depends(require_miniapp_user),
    db: Session = Depends(get_db),
) -> MonitoringResponse:
    assert_telegram_id_match(auth_user, payload.telegram_id)
    monitoring = db.scalar(
        select(Monitoring).where(and_(Monitoring.id == monitoring_id, Monitoring.user_id == auth_user.id))
    )
    if not monitoring:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Monitoring not found")
    was_active = bool(monitoring.is_active)
    prev_include_photo = bool(monitoring.include_photo)
    prev_include_description = bool(monitoring.include_description)
    prev_include_seller_info = bool(monitoring.include_seller_info)
    prev_notify_price_drop = bool(monitoring.notify_price_drop)

    if payload.title is not None:
        monitoring.title = payload.title.strip() or monitoring.title

    if payload.url is not None:
        cleaned_url = normalize_monitoring_url(payload.url)
        monitoring.url = cleaned_url
        monitoring.link_configured = bool(cleaned_url)

    if payload.is_active is not None:
        if payload.is_active and not monitoring.link_configured:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="Сначала задайте ссылку, затем включайте мониторинг",
            )
        monitoring.is_active = payload.is_active

    if payload.include_photo is not None:
        monitoring.include_photo = payload.include_photo
    if payload.include_description is not None:
        monitoring.include_description = payload.include_description
    if payload.include_seller_info is not None:
        monitoring.include_seller_info = payload.include_seller_info
    if payload.notify_price_drop is not None:
        monitoring.notify_price_drop = payload.notify_price_drop

    db.commit()
    db.refresh(monitoring)

    settings_changed = any(
        [
            payload.include_photo is not None and bool(payload.include_photo) != prev_include_photo,
            payload.include_description is not None and bool(payload.include_description) != prev_include_description,
            payload.include_seller_info is not None and bool(payload.include_seller_info) != prev_include_seller_info,
            payload.notify_price_drop is not None and bool(payload.notify_price_drop) != prev_notify_price_drop,
        ]
    )

    if settings_changed:
        db.execute(
            update(Notification)
            .where(
                and_(
                    Notification.monitoring_id == monitoring.id,
                    Notification.status == "pending",
                )
            )
            .values(
                status="sent",
                sent_at=now_utc(),
            )
        )
        db.commit()
        if monitoring.bot_id:
            purge_monitoring_notifications(int(monitoring.bot_id), int(monitoring.id))

    if was_active and not monitoring.is_active and payload.is_active is False:
        title = (monitoring.title or f"Мониторинг #{monitoring.id}").strip()
        message = (
            f"⏹ Мониторинг «{title}» остановлен через MiniApp.\n"
            "Для возобновления используйте команду /start_monitoring."
        )
        send_monitoring_bot_message(db, monitoring, auth_user.telegram_id, message)

    return _monitoring_to_schema(monitoring)


@router.post("/monitorings/purchase", response_model=MonitoringResponse)
def purchase_monitoring(
    payload: MonitoringPurchaseRequest,
    auth_user: User = Depends(require_miniapp_user),
    db: Session = Depends(get_db),
) -> MonitoringResponse:
    assert_telegram_id_match(auth_user, payload.telegram_id)
    user = auth_user
    active_sub = _require_active_subscription(db, user.id)
    links_limit = active_sub.plan.links_limit if active_sub.plan else 0
    total_before = _require_slot_available(db, user.id, links_limit)

    bot = get_available_bot_for_user(db, user.id)
    if not bot:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="Нет доступного бота для нового мониторинга. Добавьте ботов в админке.",
        )

    cleaned_url = normalize_monitoring_url(payload.url)
    link_configured = bool(cleaned_url)
    monitoring = Monitoring(
        user_id=user.id,
        bot_id=bot.id,
        url=cleaned_url or "https://www.avito.ru/",
        title=payload.title or f"Мониторинг #{total_before + 1}",
        keywords_white="",
        keywords_black="",
        min_price=None,
        max_price=None,
        geo=None,
        is_active=False,
        link_configured=link_configured,
    )
    db.add(monitoring)
    db.commit()
    db.refresh(monitoring)
    return _monitoring_to_schema(monitoring)


@router.post("/subscriptions/purchase", response_model=PurchaseSubscriptionResponse)
def purchase_subscription(
    payload: PurchaseSubscriptionRequest,
    auth_user: User = Depends(require_miniapp_user),
    db: Session = Depends(get_db),
) -> PurchaseSubscriptionResponse:
    assert_telegram_id_match(auth_user, payload.telegram_id)
    user = auth_user
    plan = db.get(TariffPlan, payload.plan_id)
    if not plan or not plan.is_active:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="План не найден или неактивен")

    target_monitoring = None
    if payload.monitoring_id is not None:
        target_monitoring = db.scalar(
            select(Monitoring).where(and_(Monitoring.id == payload.monitoring_id, Monitoring.user_id == user.id))
        )
        if not target_monitoring:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Monitoring not found")

    slots_to_add = 0 if target_monitoring else 1
    _require_free_bots_for_new_slots(db, user.id, slots_to_add)

    current_total_slots = db.scalar(select(func.count(Monitoring.id)).where(Monitoring.user_id == user.id)) or 0
    target_total_slots = current_total_slots + slots_to_add

    base_price = max(0, int(plan.price_rub))
    total_price = max(0, base_price)

    referral_used = 0
    if payload.use_referral_balance:
        current_balance = max(0, int(user.referral_balance_rub or 0))
        referral_used = min(current_balance, total_price)
        user.referral_balance_rub = current_balance - referral_used

    amount_to_pay = max(0, total_price - referral_used)
    plan_format_raw = (plan.plan_format or "").strip().lower()
    plan_subscription_type = "speed" if plan_format_raw.startswith("speed") else "standard"
    if plan_subscription_type not in {"speed", "standard"}:
        plan_subscription_type = "speed" if (payload.subscription_type or "").strip().lower().startswith("speed") else "standard"

    purchase_payload = {
        "subscription_type": plan_subscription_type,
        "duration_days": int(plan.duration_days),
        "monitoring_id": target_monitoring.id if target_monitoring else None,
        "base_price_rub": base_price,
        "speed_surcharge_rub": 0,
        "total_price_rub": total_price,
        "referral_used_rub": referral_used,
        "referral_debited": referral_used > 0,
        "referral_refunded": False,
        "target_total_slots": target_total_slots,
        "monitoring_title": payload.monitoring_title,
        "monitoring_url": payload.monitoring_url,
        "finalized": False,
    }

    if amount_to_pay <= 0:
        provider = "miniapp_speed" if plan_subscription_type == "speed" else "miniapp_standard"
        if referral_used > 0:
            provider = f"{provider}_with_ref"

        payment = Payment(
            user_id=user.id,
            plan_id=plan.id,
            amount_rub=amount_to_pay,
            status="completed",
            provider=provider,
            payload=purchase_payload,
        )
        db.add(payment)
        db.flush()
        subscription = _finalize_subscription_payment(
            db=db,
            user=user,
            plan=plan,
            payment=payment,
        )
        return _build_purchase_response(
            ok=True,
            user_id=user.id,
            plan_id=plan.id,
            amount_rub=amount_to_pay,
            referral_used_rub=referral_used,
            total_price_rub=total_price,
            subscription=subscription,
            payment=payment,
            requires_payment=False,
            payment_status="succeeded",
            message="Подписка активирована",
        )

    if not yookassa_is_configured():
        raise HTTPException(status_code=status.HTTP_503_SERVICE_UNAVAILABLE, detail="ЮKassa не настроена")

    provider = "yookassa_sbp_with_ref" if referral_used > 0 else "yookassa_sbp"
    payment = Payment(
        user_id=user.id,
        plan_id=plan.id,
        amount_rub=amount_to_pay,
        status="pending",
        provider=provider,
        payload=purchase_payload,
    )
    db.add(payment)
    db.flush()

    return_url = _append_query_param(settings.yookassa_return_url_effective, "payment_id", str(payment.id))
    try:
        yookassa_payment = create_sbp_payment(
            amount_rub=amount_to_pay,
            description=f"Подписка «{plan.name}» для {user.telegram_id}",
            return_url=return_url,
            metadata={
                "internal_payment_id": str(payment.id),
                "telegram_id": str(user.telegram_id),
                "plan_id": str(plan.id),
            },
            idempotence_key=f"miniapp-{payment.id}-{now_utc().timestamp()}",
        )
    except YooKassaError as exc:
        db.rollback()
        raise HTTPException(
            status_code=status.HTTP_502_BAD_GATEWAY,
            detail=f"Не удалось создать платеж ЮKassa: {exc}",
        ) from exc

    yookassa_status = str(yookassa_payment.get("status") or "pending").strip() or "pending"
    confirmation = yookassa_payment.get("confirmation")
    confirmation_url = (
        str(confirmation.get("confirmation_url") or "").strip()
        if isinstance(confirmation, dict)
        else ""
    )
    payment.external_id = str(yookassa_payment.get("id") or "").strip() or None
    payment_payload = _payment_payload(payment)
    payment_payload["yookassa_status"] = yookassa_status
    payment_payload["return_url"] = return_url
    payment_payload["confirmation_url"] = confirmation_url or None
    payment.payload = payment_payload

    if yookassa_status == "canceled":
        payment.status = "canceled"
        payment_payload = _refund_referral_if_needed(user, payment_payload)
        payment.payload = payment_payload
        db.commit()
        return _build_purchase_response(
            ok=False,
            user_id=user.id,
            plan_id=plan.id,
            amount_rub=amount_to_pay,
            referral_used_rub=referral_used,
            total_price_rub=total_price,
            payment=payment,
            requires_payment=False,
            payment_status="canceled",
            payment_url=confirmation_url or None,
            message="Платеж отменен",
        )

    if yookassa_status == "succeeded":
        payment.status = "completed"
        subscription = _finalize_subscription_payment(
            db=db,
            user=user,
            plan=plan,
            payment=payment,
        )
        return _build_purchase_response(
            ok=True,
            user_id=user.id,
            plan_id=plan.id,
            amount_rub=amount_to_pay,
            referral_used_rub=referral_used,
            total_price_rub=total_price,
            subscription=subscription,
            payment=payment,
            requires_payment=False,
            payment_status="succeeded",
            payment_url=confirmation_url or None,
            message="Оплата подтверждена, подписка активирована",
        )

    payment.status = "pending"
    db.commit()
    return _build_purchase_response(
        ok=True,
        user_id=user.id,
        plan_id=plan.id,
        amount_rub=amount_to_pay,
        referral_used_rub=referral_used,
        total_price_rub=total_price,
        payment=payment,
        requires_payment=True,
        payment_status=yookassa_status,
        payment_url=confirmation_url or None,
        message="Платеж создан. Завершите оплату и вернитесь в MiniApp.",
    )


@router.get("/subscriptions/purchase/{payment_id}/status", response_model=PurchaseSubscriptionResponse)
def subscription_purchase_status(
    payment_id: int,
    telegram_id: int = Query(...),
    auth_user: User = Depends(require_miniapp_user),
    db: Session = Depends(get_db),
) -> PurchaseSubscriptionResponse:
    assert_telegram_id_match(auth_user, telegram_id)
    user = auth_user
    payment = db.scalar(select(Payment).where(and_(Payment.id == payment_id, Payment.user_id == user.id)))
    if not payment:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Платеж не найден")

    plan_id = int(payment.plan_id or 0)
    if plan_id <= 0:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail="В платеже не указан тариф")
    plan = db.get(TariffPlan, plan_id)
    if not plan:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail="Тариф платежа не найден")

    payment_payload = _payment_payload(payment)
    amount_to_pay = max(0, _safe_int(payment.amount_rub, 0))
    referral_used = max(0, _safe_int(payment_payload.get("referral_used_rub"), 0))
    total_price = max(amount_to_pay + referral_used, _safe_int(payment_payload.get("total_price_rub"), amount_to_pay + referral_used))

    if payment.provider.startswith("yookassa") and payment.status not in {"completed", "canceled"} and payment.external_id:
        if not yookassa_is_configured():
            raise HTTPException(status_code=status.HTTP_503_SERVICE_UNAVAILABLE, detail="ЮKassa не настроена")
        try:
            yookassa_payment = get_yookassa_payment(payment.external_id)
        except YooKassaError as exc:
            raise HTTPException(
                status_code=status.HTTP_502_BAD_GATEWAY,
                detail=f"Не удалось проверить платеж ЮKassa: {exc}",
            ) from exc

        yookassa_status = str(yookassa_payment.get("status") or "pending").strip() or "pending"
        confirmation = yookassa_payment.get("confirmation")
        confirmation_url = (
            str(confirmation.get("confirmation_url") or "").strip()
            if isinstance(confirmation, dict)
            else ""
        )
        payment_payload["yookassa_status"] = yookassa_status
        if confirmation_url:
            payment_payload["confirmation_url"] = confirmation_url
        payment.payload = payment_payload

        if yookassa_status == "succeeded":
            payment.status = "completed"
            subscription = _finalize_subscription_payment(
                db=db,
                user=user,
                plan=plan,
                payment=payment,
            )
            return _build_purchase_response(
                ok=True,
                user_id=user.id,
                plan_id=plan.id,
                amount_rub=amount_to_pay,
                referral_used_rub=referral_used,
                total_price_rub=total_price,
                subscription=subscription,
                payment=payment,
                requires_payment=False,
                payment_status="succeeded",
                payment_url=confirmation_url or None,
                message="Оплата подтверждена, подписка активирована",
            )

        if yookassa_status == "canceled":
            payment.status = "canceled"
            payment_payload = _refund_referral_if_needed(user, payment_payload)
            payment.payload = payment_payload
            db.commit()
            return _build_purchase_response(
                ok=False,
                user_id=user.id,
                plan_id=plan.id,
                amount_rub=amount_to_pay,
                referral_used_rub=referral_used,
                total_price_rub=total_price,
                payment=payment,
                requires_payment=False,
                payment_status="canceled",
                payment_url=confirmation_url or None,
                message="Платеж отменен",
            )

        payment.status = "pending"
        db.commit()
        return _build_purchase_response(
            ok=True,
            user_id=user.id,
            plan_id=plan.id,
            amount_rub=amount_to_pay,
            referral_used_rub=referral_used,
            total_price_rub=total_price,
            payment=payment,
            requires_payment=True,
            payment_status=yookassa_status,
            payment_url=confirmation_url or None,
            message="Платеж ожидает завершения",
        )

    if payment.status == "completed":
        subscription = None
        existing_subscription_id = _safe_int(payment_payload.get("subscription_id"), 0)
        if existing_subscription_id > 0:
            subscription = db.get(UserSubscription, existing_subscription_id)
        if payment.provider.startswith("yookassa") and not subscription:
            subscription = _finalize_subscription_payment(
                db=db,
                user=user,
                plan=plan,
                payment=payment,
            )
        return _build_purchase_response(
            ok=True,
            user_id=user.id,
            plan_id=plan.id,
            amount_rub=amount_to_pay,
            referral_used_rub=referral_used,
            total_price_rub=total_price,
            subscription=subscription,
            payment=payment,
            requires_payment=False,
            payment_status=str(payment_payload.get("yookassa_status") or payment.status or "").strip() or "succeeded",
            message="Подписка активна",
        )

    if payment.status == "canceled":
        payment_payload = _refund_referral_if_needed(user, payment_payload)
        payment.payload = payment_payload
        db.commit()
        return _build_purchase_response(
            ok=False,
            user_id=user.id,
            plan_id=plan.id,
            amount_rub=amount_to_pay,
            referral_used_rub=referral_used,
            total_price_rub=total_price,
            payment=payment,
            requires_payment=False,
            payment_status="canceled",
            message="Платеж отменен",
        )

    return _build_purchase_response(
        ok=True,
        user_id=user.id,
        plan_id=plan.id,
        amount_rub=amount_to_pay,
        referral_used_rub=referral_used,
        total_price_rub=total_price,
        payment=payment,
        requires_payment=True,
        payment_status=str(payment_payload.get("yookassa_status") or payment.status or "").strip() or "pending",
        message="Платеж ожидает завершения",
    )


@webhook_router.post("/webhooks")
def yookassa_webhook(payload: dict, db: Session = Depends(get_db)) -> dict:
    event = str(payload.get("event") or "").strip().lower()
    obj = payload.get("object")
    if not isinstance(obj, dict):
        return {"ok": True, "ignored": "invalid_payload"}

    external_id = str(obj.get("id") or "").strip()
    if not external_id:
        return {"ok": True, "ignored": "missing_payment_id"}

    payment = db.scalar(select(Payment).where(Payment.external_id == external_id))
    if not payment:
        return {"ok": True, "ignored": "payment_not_found", "external_id": external_id}
    if not str(payment.provider or "").startswith("yookassa"):
        return {"ok": True, "ignored": "not_yookassa_provider", "payment_id": payment.id}

    status_value = str(obj.get("status") or "").strip().lower()
    yookassa_status = status_value or str(payment.status or "pending").strip().lower()
    payment_payload = _payment_payload(payment)
    payment_payload["last_webhook_event"] = event or None
    payment_payload["yookassa_status"] = yookassa_status
    if isinstance(obj.get("metadata"), dict):
        payment_payload["yookassa_metadata"] = obj.get("metadata")
    confirmation = obj.get("confirmation")
    if isinstance(confirmation, dict):
        confirmation_url = str(confirmation.get("confirmation_url") or "").strip()
        if confirmation_url:
            payment_payload["confirmation_url"] = confirmation_url
    payment.payload = payment_payload

    user = db.get(User, payment.user_id) if payment.user_id else None
    plan = db.get(TariffPlan, payment.plan_id) if payment.plan_id else None

    if yookassa_status == "succeeded" or event == "payment.succeeded":
        if not user or not plan:
            return {"ok": True, "ignored": "missing_user_or_plan", "payment_id": payment.id}
        payment.status = "completed"
        subscription = _finalize_subscription_payment(
            db=db,
            user=user,
            plan=plan,
            payment=payment,
        )
        return {
            "ok": True,
            "processed": "succeeded",
            "payment_id": payment.id,
            "subscription_id": subscription.id if subscription else None,
        }

    if yookassa_status == "canceled" or event == "payment.canceled":
        payment.status = "canceled"
        if user:
            payment_payload = _refund_referral_if_needed(user, payment_payload)
            payment.payload = payment_payload
        db.commit()
        return {"ok": True, "processed": "canceled", "payment_id": payment.id}

    payment.status = "pending"
    db.commit()
    return {"ok": True, "processed": "pending", "payment_id": payment.id, "status": yookassa_status}


@router.delete("/monitorings/{monitoring_id}")
def delete_monitoring(
    monitoring_id: int,
    telegram_id: int = Query(...),
    auth_user: User = Depends(require_miniapp_user),
    db: Session = Depends(get_db),
) -> dict:
    assert_telegram_id_match(auth_user, telegram_id)
    user = auth_user
    monitoring = db.scalar(
        select(Monitoring).where(and_(Monitoring.id == monitoring_id, Monitoring.user_id == user.id))
    )
    if not monitoring:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Monitoring not found")

    db.delete(monitoring)
    db.commit()
    return {"ok": True}


@router.get("/monitorings/{monitoring_id}/items", response_model=list[MonitoringItemResponse])
def monitoring_items(
    monitoring_id: int,
    telegram_id: int = Query(...),
    limit: int = Query(default=50, ge=1, le=200),
    auth_user: User = Depends(require_miniapp_user),
    db: Session = Depends(get_db),
) -> list[MonitoringItemResponse]:
    assert_telegram_id_match(auth_user, telegram_id)
    user = auth_user
    monitoring = db.scalar(
        select(Monitoring).where(and_(Monitoring.id == monitoring_id, Monitoring.user_id == user.id))
    )
    if not monitoring:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Monitoring not found")

    items = db.scalars(
        select(MonitoringItem)
        .where(MonitoringItem.monitoring_id == monitoring_id)
        .order_by(desc(MonitoringItem.first_seen_at))
        .limit(limit)
    ).all()

    return [
        MonitoringItemResponse(
            id=i.id,
            avito_ad_id=i.avito_ad_id,
            title=i.title,
            url=i.url,
            price_rub=i.price_rub,
            location=i.location,
            published_at=i.published_at,
            first_seen_at=i.first_seen_at,
        )
        for i in items
    ]


@router.get("/notifications", response_model=list[NotificationResponse])
def notifications(
    telegram_id: int = Query(...),
    limit: int = Query(default=50, ge=1, le=200),
    auth_user: User = Depends(require_miniapp_user),
    db: Session = Depends(get_db),
) -> list[NotificationResponse]:
    assert_telegram_id_match(auth_user, telegram_id)
    user = auth_user
    notifications_raw = db.scalars(
        select(Notification)
        .where(Notification.user_id == user.id)
        .order_by(desc(Notification.created_at))
        .limit(limit)
    ).all()

    return [
        NotificationResponse(
            id=n.id,
            message=n.message,
            created_at=n.created_at,
            monitoring_id=n.monitoring_id,
        )
        for n in notifications_raw
    ]
