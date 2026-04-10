from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy import and_, desc, func, select
from sqlalchemy.orm import Session

from app.database import get_db
from app.models import Monitoring, Payment, ProxyConfig, TariffPlan, TelegramBot, User, UserSubscription
from app.schemas import (
    ActivateSubscriptionRequest,
    PaymentCreate,
    PaymentResponse,
    ProxyCreate,
    ProxyResponse,
    ProxyUpdate,
    TelegramBotCreate,
    TelegramBotResponse,
    TelegramBotUpdate,
    TrialSettingsResponse,
    TrialSettingsUpdate,
    TariffPlanCreate,
    TariffPlanResponse,
    TariffPlanUpdate,
)
from app.services.auth import require_admin_token
from app.services.helpers import (
    activate_user_subscription,
    ensure_subscription_monitoring_slots,
    get_or_create_user,
    get_trial_days,
    now_utc,
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


def _ensure_primary_bot_exists(db: Session) -> None:
    existing_primary = db.scalar(select(TelegramBot).where(TelegramBot.is_primary.is_(True)))
    if existing_primary:
        return
    first_bot = db.scalar(select(TelegramBot).order_by(TelegramBot.id.asc()))
    if first_bot:
        first_bot.is_primary = True


@router.get("/stats")
def stats(db: Session = Depends(get_db)) -> dict:
    users_count = db.scalar(select(func.count(User.id))) or 0
    active_monitorings = db.scalar(
        select(func.count(Monitoring.id)).where(Monitoring.is_active.is_(True))
    ) or 0
    active_subscriptions = db.scalar(
        select(func.count(UserSubscription.id)).where(
            and_(UserSubscription.status == "active", UserSubscription.ends_at > now_utc())
        )
    ) or 0
    payments_total = db.scalar(select(func.coalesce(func.sum(Payment.amount_rub), 0)).where(Payment.status == "completed")) or 0
    active_bots = db.scalar(select(func.count(TelegramBot.id)).where(TelegramBot.is_active.is_(True))) or 0
    trial_days = get_trial_days(db)

    return {
        "users_count": users_count,
        "active_monitorings": active_monitorings,
        "active_subscriptions": active_subscriptions,
        "payments_total_rub": payments_total,
        "active_bots": active_bots,
        "trial_days": trial_days,
    }


@router.get("/trial-settings", response_model=TrialSettingsResponse)
def trial_settings(db: Session = Depends(get_db)) -> TrialSettingsResponse:
    return TrialSettingsResponse(trial_days=get_trial_days(db))


@router.put("/trial-settings", response_model=TrialSettingsResponse)
def update_trial_settings(payload: TrialSettingsUpdate, db: Session = Depends(get_db)) -> TrialSettingsResponse:
    updated_days = set_trial_days(db, payload.trial_days)
    return TrialSettingsResponse(trial_days=updated_days)


@router.get("/users")
def users(db: Session = Depends(get_db)) -> list[dict]:
    rows = db.scalars(select(User).order_by(desc(User.created_at))).all()
    result = []
    for user in rows:
        active_links = db.scalar(
            select(func.count(Monitoring.id)).where(and_(Monitoring.user_id == user.id, Monitoring.is_active.is_(True)))
        ) or 0
        result.append(
            {
                "id": user.id,
                "telegram_id": user.telegram_id,
                "username": user.username,
                "full_name": user.full_name,
                "created_at": user.created_at,
                "active_links": active_links,
            }
        )
    return result


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
                "last_checked_at": row.last_checked_at,
                "created_at": row.created_at,
            }
        )
    return result


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
    plan = TariffPlan(**payload.model_dump())
    db.add(plan)
    db.commit()
    db.refresh(plan)
    return plan


@router.put("/plans/{plan_id}", response_model=TariffPlanResponse)
def update_plan(plan_id: int, payload: TariffPlanUpdate, db: Session = Depends(get_db)) -> TariffPlan:
    plan = db.get(TariffPlan, plan_id)
    if not plan:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Plan not found")

    for key, value in payload.model_dump(exclude_none=True).items():
        setattr(plan, key, value)
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
    return list(db.scalars(select(ProxyConfig).order_by(ProxyConfig.id.asc())))


@router.post("/proxies", response_model=ProxyResponse)
def create_proxy(payload: ProxyCreate, db: Session = Depends(get_db)) -> ProxyConfig:
    proxy = ProxyConfig(**payload.model_dump())
    db.add(proxy)
    db.commit()
    db.refresh(proxy)
    return proxy


@router.put("/proxies/{proxy_id}", response_model=ProxyResponse)
def update_proxy(proxy_id: int, payload: ProxyUpdate, db: Session = Depends(get_db)) -> ProxyConfig:
    proxy = db.get(ProxyConfig, proxy_id)
    if not proxy:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Proxy not found")

    for key, value in payload.model_dump(exclude_none=True).items():
        setattr(proxy, key, value)
    db.commit()
    db.refresh(proxy)
    return proxy


@router.delete("/proxies/{proxy_id}")
def delete_proxy(proxy_id: int, db: Session = Depends(get_db)) -> dict:
    proxy = db.get(ProxyConfig, proxy_id)
    if not proxy:
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
    slots_created = ensure_subscription_monitoring_slots(db, user.id, plan.links_limit)

    return {
        "ok": True,
        "subscription_id": new_sub.id,
        "user_id": user.id,
        "plan_id": plan.id,
        "ends_at": new_sub.ends_at,
        "slots_created": slots_created,
    }
