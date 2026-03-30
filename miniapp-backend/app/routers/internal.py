from datetime import datetime

from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy import and_, desc, func, select
from sqlalchemy.orm import Session

from app.database import get_db
from app.models import Monitoring, MonitoringItem, Notification, ProxyConfig, User, UserSubscription
from app.schemas import InternalNotificationResponse, InternalScanPayload
from app.services.auth import require_internal_token
from app.services.helpers import format_new_item_message, now_utc

router = APIRouter(prefix="/internal", tags=["internal"], dependencies=[Depends(require_internal_token)])


@router.get("/monitorings/active")
def active_monitorings(db: Session = Depends(get_db)) -> list[dict]:
    monitorings = db.scalars(
        select(Monitoring)
        .where(Monitoring.is_active.is_(True))
        .order_by(Monitoring.id.asc())
    ).all()
    proxies = db.scalars(select(ProxyConfig).where(ProxyConfig.is_active.is_(True)).order_by(ProxyConfig.id.asc())).all()

    payload = []
    for mon in monitorings:
        user = db.get(User, mon.user_id)
        if not user:
            continue
        active_subscription = db.scalar(
            select(UserSubscription).where(
                and_(
                    UserSubscription.user_id == user.id,
                    UserSubscription.status == "active",
                    UserSubscription.ends_at > now_utc(),
                )
            )
        )
        if not active_subscription:
            continue
        proxy_url = None
        if proxies:
            proxy_url = proxies[mon.id % len(proxies)].proxy_url

        payload.append(
            {
                "monitoring_id": mon.id,
                "telegram_id": user.telegram_id,
                "url": mon.url,
                "title": mon.title,
                "keywords_white": [x for x in (mon.keywords_white or "").split(",") if x],
                "keywords_black": [x for x in (mon.keywords_black or "").split(",") if x],
                "min_price": mon.min_price,
                "max_price": mon.max_price,
                "geo": mon.geo,
                "proxy_url": proxy_url,
            }
        )
    return payload


@router.post("/monitorings/{monitoring_id}/scan-result")
def save_scan_result(monitoring_id: int, payload: InternalScanPayload, db: Session = Depends(get_db)) -> dict:
    monitoring = db.get(Monitoring, monitoring_id)
    if not monitoring:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Monitoring not found")

    created = 0
    touched = 0
    for item in payload.items:
        existing = db.scalar(
            select(MonitoringItem).where(
                and_(
                    MonitoringItem.monitoring_id == monitoring_id,
                    MonitoringItem.avito_ad_id == item.avito_ad_id,
                )
            )
        )
        if existing:
            existing.last_seen_at = now_utc()
            touched += 1
            continue

        db_item = MonitoringItem(
            monitoring_id=monitoring_id,
            avito_ad_id=item.avito_ad_id,
            title=item.title,
            url=item.url,
            price_rub=item.price_rub,
            location=item.location,
            published_at=item.published_at,
            raw_json=item.raw_json,
        )
        db.add(db_item)
        db.flush()

        notification = Notification(
            user_id=monitoring.user_id,
            monitoring_id=monitoring_id,
            item_id=db_item.id,
            message=format_new_item_message(
                title=db_item.title,
                price_rub=db_item.price_rub,
                url=db_item.url,
                location=db_item.location,
            ),
            status="pending",
        )
        db.add(notification)
        created += 1

    monitoring.last_checked_at = now_utc()
    db.commit()
    return {"ok": True, "created_items": created, "updated_items": touched}


@router.get("/notifications/pending", response_model=list[InternalNotificationResponse])
def pending_notifications(
    limit: int = Query(default=100, ge=1, le=500),
    db: Session = Depends(get_db),
) -> list[InternalNotificationResponse]:
    notifications = db.scalars(
        select(Notification)
        .where(Notification.status == "pending")
        .order_by(Notification.created_at.asc())
        .limit(limit)
    ).all()

    out = []
    for n in notifications:
        user = db.get(User, n.user_id)
        if not user:
            continue
        out.append(
            InternalNotificationResponse(id=n.id, telegram_id=user.telegram_id, message=n.message)
        )
    return out


@router.post("/notifications/{notification_id}/sent")
def mark_sent(notification_id: int, db: Session = Depends(get_db)) -> dict:
    notification = db.get(Notification, notification_id)
    if not notification:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Notification not found")
    notification.status = "sent"
    notification.sent_at = now_utc()
    db.commit()
    return {"ok": True}
