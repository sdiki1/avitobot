from datetime import datetime

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy import and_, desc, func, select
from sqlalchemy.orm import Session

from app.database import get_db
from app.models import Monitoring, Payment, ProxyConfig, TariffPlan, User, UserSubscription
from app.schemas import (
    ActivateSubscriptionRequest,
    PaymentCreate,
    PaymentResponse,
    ProxyCreate,
    ProxyResponse,
    ProxyUpdate,
    TariffPlanCreate,
    TariffPlanResponse,
    TariffPlanUpdate,
)
from app.services.auth import require_admin_token
from app.services.helpers import add_days, get_or_create_user, now_utc

router = APIRouter(prefix="/admin", tags=["admin"], dependencies=[Depends(require_admin_token)])


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

    return {
        "users_count": users_count,
        "active_monitorings": active_monitorings,
        "active_subscriptions": active_subscriptions,
        "payments_total_rub": payments_total,
    }


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
        result.append(
            {
                "id": row.id,
                "user_id": row.user_id,
                "url": row.url,
                "title": row.title,
                "is_active": row.is_active,
                "last_checked_at": row.last_checked_at,
                "created_at": row.created_at,
            }
        )
    return result


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

    # Закрываем предыдущую активную подписку
    active_sub = db.scalar(
        select(UserSubscription)
        .where(and_(UserSubscription.user_id == user.id, UserSubscription.status == "active", UserSubscription.ends_at > now_utc()))
        .order_by(UserSubscription.ends_at.desc())
    )
    if active_sub:
        active_sub.status = "expired"

    started = now_utc()
    new_sub = UserSubscription(
        user_id=user.id,
        plan_id=plan.id,
        status="active",
        amount_paid=plan.price_rub,
        started_at=started,
        ends_at=add_days(started, plan.duration_days),
    )
    db.add(new_sub)
    db.commit()
    db.refresh(new_sub)

    return {
        "ok": True,
        "subscription_id": new_sub.id,
        "user_id": user.id,
        "plan_id": plan.id,
        "ends_at": new_sub.ends_at,
    }
