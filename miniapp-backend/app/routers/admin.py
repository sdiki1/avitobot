from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy import and_, desc, func, select
from sqlalchemy.orm import Session

from app.database import get_db
from app.models import Monitoring, Payment, ProxyConfig, TariffPlan, TelegramBot, User, UserSubscription
from app.schemas import (
    ActivateSubscriptionRequest,
    AdminUserCreate,
    AdminUserUpdate,
    MiniAppContentResponse,
    MiniAppContentUpdate,
    MonitoringAdminUpdate,
    PaymentCreate,
    PaymentResponse,
    ProxyCreate,
    ProxyResponse,
    ProxyUpdate,
    ReferralSettingsResponse,
    ReferralSettingsUpdate,
    TariffPlanCreate,
    TariffPlanResponse,
    TariffPlanUpdate,
    TelegramBotCreate,
    TelegramBotResponse,
    TelegramBotUpdate,
    TrialSettingsResponse,
    TrialSettingsUpdate,
)
from app.services.auth import require_admin_token
from app.services.helpers import (
    activate_user_subscription,
    ensure_subscription_monitoring_slots,
    get_referral_reward_percent,
    get_miniapp_content_settings,
    get_or_create_user,
    get_trial_days,
    now_utc,
    normalize_monitoring_url,
    set_referral_reward_percent,
    set_miniapp_content_settings,
    set_trial_days,
)

router = APIRouter(prefix="/admin", tags=["admin"], dependencies=[Depends(require_admin_token)])


def _build_bot_link(username: str | None) -> str | None:
    if not username:
        return None
    return f"https://t.me/{username.lstrip('@')}"


def _bot_to_schema(bot: TelegramBot) -> TelegramBotResponse:
    return TelegramBotResponse(
        id=bot.id,
        name=bot.name,
        is_active=bot.is_active,
        is_primary=bot.is_primary,
        telegram_bot_id=bot.telegram_bot_id,
        bot_username=bot.bot_username,
        bot_link=_build_bot_link(bot.bot_username),
        created_at=bot.created_at,
        updated_at=bot.updated_at,
    )


def _set_primary_bot(db: Session, target_bot_id: int) -> None:
    bots = db.scalars(select(TelegramBot).order_by(TelegramBot.id.asc())).all()
    for bot in bots:
        bot.is_primary = bot.id == target_bot_id


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


def _ensure_primary_bot_exists(db: Session) -> None:
    existing_primary = db.scalar(select(TelegramBot).where(TelegramBot.is_primary.is_(True)))
    if existing_primary:
        return
    first_bot = db.scalar(select(TelegramBot).order_by(TelegramBot.id.asc()))
    if first_bot:
        first_bot.is_primary = True


def _normalize_plan_format(value: str | None) -> str:
    normalized = (value or "").strip().lower()
    if normalized.startswith("speed") or normalized.startswith("ускор") or normalized.startswith("скорост"):
        return "speed"
    return "standard"


def _normalize_duration_label(value: str | None, duration_days: int) -> str:
    label = (value or "").strip()
    if label:
        return label
    return f"{int(duration_days)} дней"


@router.get("/stats")
def stats(db: Session = Depends(get_db)) -> dict:
    users_count = db.scalar(select(func.count(User.id))) or 0
    active_monitorings = db.scalar(
        select(func.count(Monitoring.id)).where(Monitoring.is_active.is_(True))
    ) or 0
    active_subscriptions = db.scalar(
        select(func.count(UserSubscription.id)).where(
            UserSubscription.ends_at > now_utc()
        )
    ) or 0
    payments_total = db.scalar(select(func.coalesce(func.sum(Payment.amount_rub), 0)).where(Payment.status == "completed")) or 0
    active_bots = db.scalar(select(func.count(TelegramBot.id)).where(TelegramBot.is_active.is_(True))) or 0
    trial_days = get_trial_days(db)
    referral_reward_percent = get_referral_reward_percent(db)

    return {
        "users_count": users_count,
        "active_monitorings": active_monitorings,
        "active_subscriptions": active_subscriptions,
        "payments_total_rub": payments_total,
        "active_bots": active_bots,
        "trial_days": trial_days,
        "referral_reward_percent": referral_reward_percent,
    }


@router.get("/trial-settings", response_model=TrialSettingsResponse)
def trial_settings(db: Session = Depends(get_db)) -> TrialSettingsResponse:
    return TrialSettingsResponse(trial_days=get_trial_days(db))


@router.put("/trial-settings", response_model=TrialSettingsResponse)
def update_trial_settings(payload: TrialSettingsUpdate, db: Session = Depends(get_db)) -> TrialSettingsResponse:
    updated_days = set_trial_days(db, payload.trial_days)
    return TrialSettingsResponse(trial_days=updated_days)


@router.get("/referral-settings", response_model=ReferralSettingsResponse)
def referral_settings(db: Session = Depends(get_db)) -> ReferralSettingsResponse:
    return ReferralSettingsResponse(referral_reward_percent=get_referral_reward_percent(db))


@router.put("/referral-settings", response_model=ReferralSettingsResponse)
def update_referral_settings(
    payload: ReferralSettingsUpdate,
    db: Session = Depends(get_db),
) -> ReferralSettingsResponse:
    updated_percent = set_referral_reward_percent(db, payload.referral_reward_percent)
    return ReferralSettingsResponse(referral_reward_percent=updated_percent)


@router.get("/miniapp-content", response_model=MiniAppContentResponse)
def get_miniapp_content(db: Session = Depends(get_db)) -> MiniAppContentResponse:
    values = get_miniapp_content_settings(db)
    return _miniapp_content_response(values)


@router.put("/miniapp-content", response_model=MiniAppContentResponse)
def update_miniapp_content(payload: MiniAppContentUpdate, db: Session = Depends(get_db)) -> MiniAppContentResponse:
    values = set_miniapp_content_settings(
        db,
        {
            "miniapp_info_support_title": payload.support_title,
            "miniapp_info_support_url": payload.support_url,
            "miniapp_info_faq_title": payload.faq_title,
            "miniapp_info_faq_url": payload.faq_url,
            "miniapp_info_news_title": payload.news_title,
            "miniapp_info_news_url": payload.news_url,
            "miniapp_info_terms_title": payload.terms_title,
            "miniapp_info_terms_url": payload.terms_url,
            "miniapp_info_privacy_title": payload.privacy_title,
            "miniapp_info_privacy_url": payload.privacy_url,
            "miniapp_subscriptions_title": payload.subscriptions_title,
            "miniapp_subscriptions_hint": payload.subscriptions_hint,
            "miniapp_profile_title": payload.profile_title,
        },
    )
    return _miniapp_content_response(values)


@router.get("/users")
def users(db: Session = Depends(get_db)) -> list[dict]:
    rows = db.scalars(select(User).order_by(desc(User.created_at))).all()
    active_links_by_user_id = {
        int(user_id): int(total or 0)
        for user_id, total in db.execute(
            select(Monitoring.user_id, func.count(Monitoring.id))
            .where(Monitoring.is_active.is_(True))
            .group_by(Monitoring.user_id)
        ).all()
        if user_id is not None
    }
    referrals_count_by_user_id = {
        int(referrer_id): int(total or 0)
        for referrer_id, total in db.execute(
            select(User.referred_by_user_id, func.count(User.id))
            .where(User.referred_by_user_id.is_not(None))
            .group_by(User.referred_by_user_id)
        ).all()
        if referrer_id is not None
    }
    referrer_ids = {int(user.referred_by_user_id) for user in rows if user.referred_by_user_id is not None}
    referrer_by_id: dict[int, User] = {}
    if referrer_ids:
        referrer_by_id = {
            int(referrer.id): referrer
            for referrer in db.scalars(select(User).where(User.id.in_(referrer_ids))).all()
        }

    result = []
    for user in rows:
        active_links = active_links_by_user_id.get(int(user.id), 0)
        referrer = referrer_by_id.get(int(user.referred_by_user_id)) if user.referred_by_user_id is not None else None
        result.append(
            {
                "id": user.id,
                "telegram_id": user.telegram_id,
                "username": user.username,
                "full_name": user.full_name,
                "created_at": user.created_at,
                "active_links": active_links,
                "is_admin": user.is_admin,
                "referral_code": user.referral_code,
                "referral_balance_rub": user.referral_balance_rub,
                "referred_by_user_id": user.referred_by_user_id,
                "referred_by_telegram_id": referrer.telegram_id if referrer else None,
                "referred_by_username": referrer.username if referrer else None,
                "referred_by_full_name": referrer.full_name if referrer else None,
                "referrals_count": referrals_count_by_user_id.get(int(user.id), 0),
            }
        )
    return result


@router.post("/users/admins")
def add_admin_user(payload: AdminUserCreate, db: Session = Depends(get_db)) -> dict:
    user = get_or_create_user(
        db,
        payload.telegram_id,
        username=(payload.username or None),
        full_name=(payload.full_name or None),
    )
    if not user.is_admin:
        user.is_admin = True
        db.commit()
        db.refresh(user)

    return {
        "id": user.id,
        "telegram_id": user.telegram_id,
        "username": user.username,
        "full_name": user.full_name,
        "is_admin": user.is_admin,
    }


@router.put("/users/{user_id}/admin")
def update_user_admin(user_id: int, payload: AdminUserUpdate, db: Session = Depends(get_db)) -> dict:
    user = db.get(User, user_id)
    if not user:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="User not found")

    user.is_admin = payload.is_admin
    db.commit()
    db.refresh(user)
    return {
        "id": user.id,
        "telegram_id": user.telegram_id,
        "username": user.username,
        "full_name": user.full_name,
        "is_admin": user.is_admin,
    }


@router.get("/monitorings")
def monitorings(db: Session = Depends(get_db)) -> list[dict]:
    rows = db.scalars(select(Monitoring).order_by(desc(Monitoring.created_at))).all()
    result = []
    for row in rows:
        bot_name = row.bot.name if row.bot else None
        bot_link = _build_bot_link(row.bot.bot_username) if row.bot else None
        result.append(
            {
                "id": row.id,
                "user_id": row.user_id,
                "bot_id": row.bot_id,
                "bot_name": bot_name,
                "bot_link": bot_link,
                "url": row.url,
                "title": row.title,
                "is_active": row.is_active,
                "link_configured": row.link_configured,
                "include_photo": row.include_photo,
                "include_description": row.include_description,
                "include_seller_info": row.include_seller_info,
                "notify_price_drop": row.notify_price_drop,
                "last_checked_at": row.last_checked_at,
                "created_at": row.created_at,
            }
        )
    return result


@router.put("/monitorings/{monitoring_id}")
def update_monitoring(monitoring_id: int, payload: MonitoringAdminUpdate, db: Session = Depends(get_db)) -> dict:
    monitoring = db.get(Monitoring, monitoring_id)
    if not monitoring:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Monitoring not found")

    if payload.title is not None:
        monitoring.title = payload.title.strip() or monitoring.title

    if payload.url is not None:
        cleaned_url = normalize_monitoring_url(payload.url)
        monitoring.url = cleaned_url
        monitoring.link_configured = bool(cleaned_url)

    if payload.is_active is not None:
        if payload.is_active and not monitoring.link_configured:
            raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Сначала задайте ссылку")
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
    bot_name = monitoring.bot.name if monitoring.bot else None
    bot_link = _build_bot_link(monitoring.bot.bot_username) if monitoring.bot else None
    return {
        "id": monitoring.id,
        "user_id": monitoring.user_id,
        "bot_id": monitoring.bot_id,
        "bot_name": bot_name,
        "bot_link": bot_link,
        "url": monitoring.url,
        "title": monitoring.title,
        "is_active": monitoring.is_active,
        "link_configured": monitoring.link_configured,
        "include_photo": monitoring.include_photo,
        "include_description": monitoring.include_description,
        "include_seller_info": monitoring.include_seller_info,
        "notify_price_drop": monitoring.notify_price_drop,
        "last_checked_at": monitoring.last_checked_at,
        "created_at": monitoring.created_at,
    }


@router.get("/bots", response_model=list[TelegramBotResponse])
def list_bots(db: Session = Depends(get_db)) -> list[TelegramBotResponse]:
    bots = db.scalars(select(TelegramBot).order_by(TelegramBot.id.asc())).all()
    return [_bot_to_schema(bot) for bot in bots]


@router.post("/bots", response_model=TelegramBotResponse)
def create_bot(payload: TelegramBotCreate, db: Session = Depends(get_db)) -> TelegramBotResponse:
    existing_name = db.scalar(select(TelegramBot).where(TelegramBot.name == payload.name))
    if existing_name:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Bot name already exists")

    existing_token = db.scalar(select(TelegramBot).where(TelegramBot.bot_token == payload.bot_token))
    if existing_token:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Bot token already exists")

    bot = TelegramBot(
        name=payload.name.strip(),
        bot_token=payload.bot_token.strip(),
        is_active=payload.is_active,
        is_primary=payload.is_primary,
    )
    db.add(bot)
    db.flush()
    if payload.is_primary:
        _set_primary_bot(db, bot.id)
    else:
        _ensure_primary_bot_exists(db)
    db.commit()
    db.refresh(bot)
    return _bot_to_schema(bot)


@router.put("/bots/{bot_id}", response_model=TelegramBotResponse)
def update_bot(bot_id: int, payload: TelegramBotUpdate, db: Session = Depends(get_db)) -> TelegramBotResponse:
    bot = db.get(TelegramBot, bot_id)
    if not bot:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Bot not found")

    if payload.name is not None:
        existing_name = db.scalar(select(TelegramBot).where(and_(TelegramBot.name == payload.name, TelegramBot.id != bot_id)))
        if existing_name:
            raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Bot name already exists")
        bot.name = payload.name.strip()

    if payload.bot_token is not None:
        token = payload.bot_token.strip()
        existing_token = db.scalar(select(TelegramBot).where(and_(TelegramBot.bot_token == token, TelegramBot.id != bot_id)))
        if existing_token:
            raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Bot token already exists")
        bot.bot_token = token

    if payload.telegram_bot_id is not None:
        existing_telegram_id = db.scalar(
            select(TelegramBot).where(
                and_(TelegramBot.telegram_bot_id == payload.telegram_bot_id, TelegramBot.id != bot_id)
            )
        )
        if existing_telegram_id:
            raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="telegram_bot_id already exists")
        bot.telegram_bot_id = payload.telegram_bot_id

    if payload.bot_username is not None:
        bot.bot_username = payload.bot_username.strip().lstrip("@") or None

    if payload.is_active is not None:
        bot.is_active = payload.is_active

    if payload.is_primary is not None:
        if payload.is_primary:
            _set_primary_bot(db, bot.id)
        else:
            bot.is_primary = False
            _ensure_primary_bot_exists(db)

    db.commit()
    db.refresh(bot)
    return _bot_to_schema(bot)


@router.delete("/bots/{bot_id}")
def delete_bot(bot_id: int, db: Session = Depends(get_db)) -> dict:
    bot = db.get(TelegramBot, bot_id)
    if not bot:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Bot not found")
    deleting_primary = bot.is_primary
    db.delete(bot)
    db.flush()
    if deleting_primary:
        _ensure_primary_bot_exists(db)
    db.commit()
    return {"ok": True}


@router.get("/plans", response_model=list[TariffPlanResponse])
def list_plans(db: Session = Depends(get_db)) -> list[TariffPlan]:
    return list(db.scalars(select(TariffPlan).order_by(TariffPlan.id.asc())))


@router.post("/plans", response_model=TariffPlanResponse)
def create_plan(payload: TariffPlanCreate, db: Session = Depends(get_db)) -> TariffPlan:
    payload_data = payload.model_dump()
    payload_data["plan_format"] = _normalize_plan_format(payload_data.get("plan_format"))
    payload_data["duration_label"] = _normalize_duration_label(payload_data.get("duration_label"), int(payload_data["duration_days"]))
    plan = TariffPlan(**payload_data)
    db.add(plan)
    db.commit()
    db.refresh(plan)
    return plan


@router.put("/plans/{plan_id}", response_model=TariffPlanResponse)
def update_plan(plan_id: int, payload: TariffPlanUpdate, db: Session = Depends(get_db)) -> TariffPlan:
    plan = db.get(TariffPlan, plan_id)
    if not plan:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Plan not found")

    update_data = payload.model_dump(exclude_none=True)
    if "plan_format" in update_data:
        update_data["plan_format"] = _normalize_plan_format(update_data.get("plan_format"))
    if "duration_label" in update_data:
        duration_days = int(update_data.get("duration_days") or plan.duration_days)
        update_data["duration_label"] = _normalize_duration_label(update_data.get("duration_label"), duration_days)

    for key, value in update_data.items():
        setattr(plan, key, value)
    if not (plan.duration_label or "").strip():
        plan.duration_label = _normalize_duration_label(None, int(plan.duration_days))
    db.commit()
    db.refresh(plan)
    return plan


@router.delete("/plans/{plan_id}")
def delete_plan(plan_id: int, db: Session = Depends(get_db)) -> dict:
    plan = db.get(TariffPlan, plan_id)
    if not plan:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Plan not found")
    db.delete(plan)
    db.commit()
    return {"ok": True}


@router.get("/proxies", response_model=list[ProxyResponse])
def list_proxies(db: Session = Depends(get_db)) -> list[ProxyConfig]:
    return list(
        db.scalars(
            select(ProxyConfig)
            .where(ProxyConfig.name.notlike("env-proxy-%"))
            .order_by(ProxyConfig.id.asc())
        )
    )


@router.post("/proxies", response_model=ProxyResponse)
def create_proxy(payload: ProxyCreate, db: Session = Depends(get_db)) -> ProxyConfig:
    normalized_name = (payload.name or "").strip()
    if normalized_name.startswith("env-proxy-"):
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Reserved proxy name prefix")

    proxy = ProxyConfig(
        name=normalized_name,
        proxy_url=payload.proxy_url,
        change_ip_url=payload.change_ip_url,
        is_active=payload.is_active,
        expires_on=payload.expires_on,
    )
    db.add(proxy)
    db.commit()
    db.refresh(proxy)
    return proxy


@router.put("/proxies/{proxy_id}", response_model=ProxyResponse)
def update_proxy(proxy_id: int, payload: ProxyUpdate, db: Session = Depends(get_db)) -> ProxyConfig:
    proxy = db.get(ProxyConfig, proxy_id)
    if not proxy:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Proxy not found")
    if (proxy.name or "").startswith("env-proxy-"):
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Proxy not found")

    payload_data = payload.model_dump(exclude_unset=True)
    if "name" in payload_data:
        next_name = (payload_data.get("name") or "").strip()
        if next_name.startswith("env-proxy-"):
            raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Reserved proxy name prefix")
        payload_data["name"] = next_name
    old_expires_on = proxy.expires_on
    for key, value in payload_data.items():
        setattr(proxy, key, value)
    if "expires_on" in payload_data and payload_data.get("expires_on") != old_expires_on:
        proxy.expiry_notified_at = None
    db.commit()
    db.refresh(proxy)
    return proxy


@router.delete("/proxies/{proxy_id}")
def delete_proxy(proxy_id: int, db: Session = Depends(get_db)) -> dict:
    proxy = db.get(ProxyConfig, proxy_id)
    if not proxy:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Proxy not found")
    if (proxy.name or "").startswith("env-proxy-"):
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Proxy not found")
    db.delete(proxy)
    db.commit()
    return {"ok": True}


@router.get("/payments", response_model=list[PaymentResponse])
def list_payments(db: Session = Depends(get_db)) -> list[Payment]:
    return list(db.scalars(select(Payment).order_by(desc(Payment.created_at))))


@router.post("/payments", response_model=PaymentResponse)
def create_payment(payload: PaymentCreate, db: Session = Depends(get_db)) -> Payment:
    user = get_or_create_user(db, payload.telegram_id, username=None, full_name=None)
    payment = Payment(
        user_id=user.id,
        plan_id=payload.plan_id,
        amount_rub=payload.amount_rub,
        status="completed",
        provider=payload.provider,
    )
    db.add(payment)
    db.commit()
    db.refresh(payment)
    return payment


@router.post("/subscriptions/activate")
def activate_subscription(payload: ActivateSubscriptionRequest, db: Session = Depends(get_db)) -> dict:
    user = get_or_create_user(db, payload.telegram_id, username=None, full_name=None)
    plan = db.get(TariffPlan, payload.plan_id)
    if not plan:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Plan not found")
    new_sub = activate_user_subscription(db, user.id, plan)
    current_total_slots = db.scalar(
        select(func.count(Monitoring.id)).where(
            and_(
                Monitoring.user_id == user.id,
                Monitoring.bot_id.is_not(None),
            )
        )
    ) or 0
    slots_created = ensure_subscription_monitoring_slots(db, user.id, current_total_slots + 1)

    return {
        "ok": True,
        "subscription_id": new_sub.id,
        "user_id": user.id,
        "plan_id": plan.id,
        "ends_at": new_sub.ends_at,
        "slots_created": slots_created,
    }
