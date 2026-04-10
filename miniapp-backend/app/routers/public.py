from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy import and_, desc, func, select
from sqlalchemy.orm import Session

from app.database import get_db
from app.models import Monitoring, MonitoringItem, Notification, Payment, TariffPlan, TelegramBot, User, UserSubscription
from app.schemas import (
    BotReference,
    MiniAppContentResponse,
    MonitoringCreate,
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
    ensure_subscription_monitoring_slots,
    ensure_user_referral_code,
    get_miniapp_content_settings,
    get_active_subscription_query,
    get_available_bot_for_user,
    get_or_create_user,
    get_trial_days,
    parse_miniapp_auth_token,
    send_subscription_assigned_bot_message,
)

router = APIRouter(prefix="/public", tags=["public"])
ONBOARDING_TRIAL_DAYS = 2


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
        url=mon.url,
        title=mon.title,
        keywords_white=[x for x in (mon.keywords_white or "").split(",") if x],
        keywords_black=[x for x in (mon.keywords_black or "").split(",") if x],
        min_price=mon.min_price,
        max_price=mon.max_price,
        geo=mon.geo,
        is_active=mon.is_active,
        link_configured=mon.link_configured,
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


def _require_user(db: Session, telegram_id: int) -> User:
    user = db.scalar(select(User).where(User.telegram_id == telegram_id))
    if not user:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="User not found")
    return user


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
            provider="onboarding_trial",
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
    return subscription


@router.post("/auth/telegram", response_model=UserResponse)
def telegram_auth(payload: TelegramAuthRequest, db: Session = Depends(get_db)) -> User:
    user = get_or_create_user(
        db,
        telegram_id=payload.telegram_id,
        username=payload.username,
        full_name=payload.full_name,
    )
    user = ensure_user_referral_code(db, user)
    return user


@router.get("/auth/resolve", response_model=TelegramAuthResolveResponse)
def resolve_auth(auth: str = Query(...), db: Session = Depends(get_db)) -> TelegramAuthResolveResponse:
    telegram_id = parse_miniapp_auth_token(auth)
    if telegram_id is None:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Invalid auth token")
    user = get_or_create_user(db, telegram_id=telegram_id, username=None, full_name=None)
    user = ensure_user_referral_code(db, user)
    return TelegramAuthResolveResponse(
        telegram_id=telegram_id,
        user=UserResponse.model_validate(user),
    )


@router.post("/onboarding-trial", response_model=OnboardingTrialResponse)
def onboarding_trial(payload: OnboardingTrialRequest, db: Session = Depends(get_db)) -> OnboardingTrialResponse:
    user = get_or_create_user(db, payload.telegram_id, username=None, full_name=None)
    user = ensure_user_referral_code(db, user)
    subscription = _activate_onboarding_trial(db, user)
    if not subscription:
        return OnboardingTrialResponse(granted=False, days=ONBOARDING_TRIAL_DAYS, ends_at=None)
    return OnboardingTrialResponse(granted=True, days=ONBOARDING_TRIAL_DAYS, ends_at=subscription.ends_at)


@router.get("/plans", response_model=list[TariffPlanResponse])
def list_plans(db: Session = Depends(get_db)) -> list[TariffPlan]:
    return list(db.scalars(select(TariffPlan).where(TariffPlan.is_active.is_(True)).order_by(TariffPlan.price_rub.asc())))


@router.get("/miniapp-content", response_model=MiniAppContentResponse)
def miniapp_content(db: Session = Depends(get_db)) -> MiniAppContentResponse:
    values = get_miniapp_content_settings(db)
    return _miniapp_content_response(values)


@router.get("/profile")
def profile(telegram_id: int = Query(...), db: Session = Depends(get_db)) -> dict:
    user = _require_user(db, telegram_id)
    user = ensure_user_referral_code(db, user)
    subscription = db.scalar(get_active_subscription_query(user.id))
    monitorings_total = db.scalar(select(func.count(Monitoring.id)).where(Monitoring.user_id == user.id))
    active_monitorings = db.scalar(
        select(func.count(Monitoring.id)).where(and_(Monitoring.user_id == user.id, Monitoring.is_active.is_(True)))
    )
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
    return payload


@router.get("/monitorings", response_model=list[MonitoringResponse])
def list_monitorings(telegram_id: int = Query(...), db: Session = Depends(get_db)) -> list[MonitoringResponse]:
    user = _require_user(db, telegram_id)
    monitorings = db.scalars(select(Monitoring).where(Monitoring.user_id == user.id).order_by(Monitoring.id.desc())).all()
    return [_monitoring_to_schema(m) for m in monitorings]


@router.post("/monitorings", response_model=MonitoringResponse)
def create_monitoring(payload: MonitoringCreate, db: Session = Depends(get_db)) -> MonitoringResponse:
    user = _require_user(db, payload.telegram_id)
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

    monitoring = Monitoring(
        user_id=user.id,
        bot_id=bot.id,
        url=payload.url.strip(),
        title=payload.title,
        keywords_white=",".join(payload.keywords_white),
        keywords_black=",".join(payload.keywords_black),
        min_price=payload.min_price,
        max_price=payload.max_price,
        geo=payload.geo,
        is_active=True,
        link_configured=True,
    )
    db.add(monitoring)
    db.commit()
    db.refresh(monitoring)
    return _monitoring_to_schema(monitoring)


@router.post("/monitorings/purchase", response_model=MonitoringResponse)
def purchase_monitoring(payload: MonitoringPurchaseRequest, db: Session = Depends(get_db)) -> MonitoringResponse:
    user = _require_user(db, payload.telegram_id)
    active_sub = _require_active_subscription(db, user.id)
    links_limit = active_sub.plan.links_limit if active_sub.plan else 0
    total_before = _require_slot_available(db, user.id, links_limit)

    bot = get_available_bot_for_user(db, user.id)
    if not bot:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="Нет доступного бота для нового мониторинга. Добавьте ботов в админке.",
        )

    cleaned_url = (payload.url or "").strip()
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
    db: Session = Depends(get_db),
) -> PurchaseSubscriptionResponse:
    user = get_or_create_user(db, payload.telegram_id, username=None, full_name=None)
    plan = db.get(TariffPlan, payload.plan_id)
    if not plan or not plan.is_active:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="План не найден или неактивен")

    existing_subscriptions = db.scalar(select(func.count(UserSubscription.id)).where(UserSubscription.user_id == user.id)) or 0
    trial_days = get_trial_days(db)
    use_trial = trial_days > 0 and existing_subscriptions == 0

    slots_to_add = 1
    _require_free_bots_for_new_slots(db, user.id, slots_to_add)

    current_total_slots = db.scalar(select(func.count(Monitoring.id)).where(Monitoring.user_id == user.id)) or 0
    target_total_slots = current_total_slots + slots_to_add

    payment = Payment(
        user_id=user.id,
        plan_id=plan.id,
        amount_rub=0 if use_trial else plan.price_rub,
        status="completed",
        provider="trial" if use_trial else "miniapp",
    )
    db.add(payment)
    subscription = activate_user_subscription(
        db,
        user.id,
        plan,
        duration_days_override=trial_days if use_trial else None,
        amount_paid_override=0 if use_trial else plan.price_rub,
        is_trial=use_trial,
    )
    ensure_subscription_monitoring_slots(db, user.id, target_total_slots)
    send_subscription_assigned_bot_message(db, user)
    return PurchaseSubscriptionResponse(
        ok=True,
        subscription_id=subscription.id,
        user_id=user.id,
        plan_id=plan.id,
        ends_at=subscription.ends_at,
        is_trial=subscription.is_trial,
    )


@router.delete("/monitorings/{monitoring_id}")
def delete_monitoring(
    monitoring_id: int,
    telegram_id: int = Query(...),
    db: Session = Depends(get_db),
) -> dict:
    user = _require_user(db, telegram_id)
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
    db: Session = Depends(get_db),
) -> list[MonitoringItemResponse]:
    user = _require_user(db, telegram_id)
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
    db: Session = Depends(get_db),
) -> list[NotificationResponse]:
    user = _require_user(db, telegram_id)
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
