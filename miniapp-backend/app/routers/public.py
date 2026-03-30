from datetime import datetime

from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy import Select, and_, desc, func, select
from sqlalchemy.orm import Session

from app.database import get_db
from app.models import Monitoring, MonitoringItem, Notification, TariffPlan, User, UserSubscription
from app.schemas import (
    MonitoringCreate,
    MonitoringItemResponse,
    MonitoringResponse,
    NotificationResponse,
    TariffPlanResponse,
    TelegramAuthRequest,
    UserResponse,
)
from app.services.helpers import get_active_subscription_query, get_or_create_user

router = APIRouter(prefix="/public", tags=["public"])


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
        last_checked_at=mon.last_checked_at,
    )


def _require_user(db: Session, telegram_id: int) -> User:
    user = db.scalar(select(User).where(User.telegram_id == telegram_id))
    if not user:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="User not found")
    return user


@router.post("/auth/telegram", response_model=UserResponse)
def telegram_auth(payload: TelegramAuthRequest, db: Session = Depends(get_db)) -> User:
    user = get_or_create_user(
        db,
        telegram_id=payload.telegram_id,
        username=payload.username,
        full_name=payload.full_name,
    )
    return user


@router.get("/plans", response_model=list[TariffPlanResponse])
def list_plans(db: Session = Depends(get_db)) -> list[TariffPlan]:
    return list(db.scalars(select(TariffPlan).where(TariffPlan.is_active.is_(True)).order_by(TariffPlan.price_rub.asc())))


@router.get("/profile")
def profile(telegram_id: int = Query(...), db: Session = Depends(get_db)) -> dict:
    user = _require_user(db, telegram_id)
    subscription = db.scalar(get_active_subscription_query(user.id))
    monitorings_count = db.scalar(
        select(func.count(Monitoring.id)).where(and_(Monitoring.user_id == user.id, Monitoring.is_active.is_(True)))
    )

    payload = {
        "user": UserResponse.model_validate(user),
        "active_monitorings": monitorings_count or 0,
        "subscription": None,
    }
    if subscription:
        payload["subscription"] = {
            "id": subscription.id,
            "plan_id": subscription.plan_id,
            "ends_at": subscription.ends_at,
            "status": subscription.status,
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
    active_sub = db.scalar(get_active_subscription_query(user.id))
    if not active_sub:
        raise HTTPException(
            status_code=status.HTTP_402_PAYMENT_REQUIRED,
            detail="Нет активной подписки. Выберите тариф в miniapp или через админа.",
        )

    links_limit = active_sub.plan.links_limit if active_sub.plan else 0
    active_links = db.scalar(
        select(func.count(Monitoring.id)).where(and_(Monitoring.user_id == user.id, Monitoring.is_active.is_(True)))
    )
    if active_links >= links_limit:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"Лимит ссылок по тарифу исчерпан ({links_limit})",
        )

    monitoring = Monitoring(
        user_id=user.id,
        url=payload.url.strip(),
        title=payload.title,
        keywords_white=",".join(payload.keywords_white),
        keywords_black=",".join(payload.keywords_black),
        min_price=payload.min_price,
        max_price=payload.max_price,
        geo=payload.geo,
        is_active=True,
    )
    db.add(monitoring)
    db.commit()
    db.refresh(monitoring)
    return _monitoring_to_schema(monitoring)


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
