from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy import and_, select
from sqlalchemy.orm import Session

from app.database import get_db
from app.models import Monitoring, MonitoringItem, Notification, ProxyConfig, TelegramBot, User, UserSubscription
from app.schemas import (
    InternalBotCommandRequest,
    InternalBotConfigResponse,
    InternalBotLookupResponse,
    InternalBotSyncRequest,
    InternalNotificationResponse,
    InternalScanPayload,
)
from app.services.auth import require_internal_token
from app.services.helpers import (
    extract_item_description,
    extract_item_photo_url,
    format_new_item_message,
    format_price_change_message,
    get_active_subscription_query,
    now_utc,
)

router = APIRouter(prefix="/internal", tags=["internal"], dependencies=[Depends(require_internal_token)])


def _to_bot_lookup_schema(monitoring: Monitoring) -> InternalBotLookupResponse:
    return InternalBotLookupResponse(
        monitoring_id=monitoring.id,
        title=monitoring.title,
        url=monitoring.url,
        is_active=monitoring.is_active,
        link_configured=monitoring.link_configured,
    )


def _resolve_user_monitoring(db: Session, telegram_id: int, bot_id: int) -> Monitoring:
    user = db.scalar(select(User).where(User.telegram_id == telegram_id))
    if not user:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="User not found")

    monitoring = db.scalar(
        select(Monitoring)
        .where(and_(Monitoring.user_id == user.id, Monitoring.bot_id == bot_id))
        .order_by(Monitoring.id.desc())
    )
    if not monitoring:
        bot = db.get(TelegramBot, bot_id)
        if not bot or not bot.is_active:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Bot not found")
        if bot.is_primary:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="Этот бот не используется для мониторинга",
            )
        _require_active_subscription(db, user.id)
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Для этого бота нет назначенной подписки. Купите новую подписку в miniapp.",
        )
    return monitoring


def _require_active_subscription(db: Session, user_id: int) -> UserSubscription:
    active_sub = db.scalar(get_active_subscription_query(user_id))
    if not active_sub:
        raise HTTPException(status_code=status.HTTP_402_PAYMENT_REQUIRED, detail="Нет активной подписки")
    return active_sub


@router.get("/bots/active", response_model=list[InternalBotConfigResponse])
def active_bots(db: Session = Depends(get_db)) -> list[InternalBotConfigResponse]:
    bots = db.scalars(select(TelegramBot).where(TelegramBot.is_active.is_(True)).order_by(TelegramBot.id.asc())).all()
    return [
        InternalBotConfigResponse(
            id=bot.id,
            name=bot.name,
            bot_token=bot.bot_token,
            is_primary=bot.is_primary,
            telegram_bot_id=bot.telegram_bot_id,
            bot_username=bot.bot_username,
        )
        for bot in bots
    ]


@router.post("/bots/{bot_id}/sync")
def sync_bot(bot_id: int, payload: InternalBotSyncRequest, db: Session = Depends(get_db)) -> dict:
    bot = db.get(TelegramBot, bot_id)
    if not bot:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Bot not found")
    bot.telegram_bot_id = payload.telegram_bot_id
    bot.bot_username = payload.bot_username.lstrip("@") if payload.bot_username else None
    db.commit()
    return {"ok": True}


@router.get("/monitorings/active")
def active_monitorings(db: Session = Depends(get_db)) -> list[dict]:
    monitorings = db.scalars(
        select(Monitoring)
        .where(
            and_(
                Monitoring.is_active.is_(True),
                Monitoring.link_configured.is_(True),
            )
        )
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
    price_changes = 0
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
            old_price = existing.price_rub
            new_price = item.price_rub
            price_changed = old_price != new_price

            existing.title = item.title
            existing.url = item.url
            existing.price_rub = item.price_rub
            existing.location = item.location
            existing.published_at = item.published_at
            existing.raw_json = item.raw_json
            existing.last_seen_at = now_utc()

            if price_changed:
                notification = Notification(
                    user_id=monitoring.user_id,
                    monitoring_id=monitoring_id,
                    item_id=existing.id,
                    message=format_price_change_message(
                        title=existing.title,
                        old_price_rub=old_price,
                        new_price_rub=new_price,
                        url=existing.url,
                        published_at=existing.published_at,
                        avito_ad_id=existing.avito_ad_id,
                        location=existing.location,
                        description=extract_item_description(existing.raw_json),
                        raw_json=existing.raw_json,
                    ),
                    status="pending",
                )
                db.add(notification)
                price_changes += 1

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
                published_at=db_item.published_at,
                avito_ad_id=db_item.avito_ad_id,
                location=db_item.location,
                description=extract_item_description(db_item.raw_json),
                raw_json=db_item.raw_json,
            ),
            status="pending",
        )
        db.add(notification)
        created += 1

    monitoring.last_checked_at = now_utc()
    db.commit()
    return {"ok": True, "created_items": created, "updated_items": touched, "price_changes": price_changes}


@router.get("/bot-monitoring/current", response_model=InternalBotLookupResponse)
def bot_current_monitoring(
    telegram_id: int = Query(...),
    bot_id: int = Query(...),
    db: Session = Depends(get_db),
) -> InternalBotLookupResponse:
    monitoring = _resolve_user_monitoring(db, telegram_id=telegram_id, bot_id=bot_id)
    return _to_bot_lookup_schema(monitoring)


@router.post("/bot-monitoring/start", response_model=InternalBotLookupResponse)
def bot_start_monitoring(payload: InternalBotCommandRequest, db: Session = Depends(get_db)) -> InternalBotLookupResponse:
    monitoring = _resolve_user_monitoring(db, telegram_id=payload.telegram_id, bot_id=payload.bot_id)
    _require_active_subscription(db, monitoring.user_id)
    if not monitoring.link_configured:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Сначала задайте ссылку командой /change_link https://www.avito.ru/...",
        )
    monitoring.is_active = True
    db.commit()
    db.refresh(monitoring)
    return _to_bot_lookup_schema(monitoring)


@router.post("/bot-monitoring/stop", response_model=InternalBotLookupResponse)
def bot_stop_monitoring(payload: InternalBotCommandRequest, db: Session = Depends(get_db)) -> InternalBotLookupResponse:
    monitoring = _resolve_user_monitoring(db, telegram_id=payload.telegram_id, bot_id=payload.bot_id)
    monitoring.is_active = False
    db.commit()
    db.refresh(monitoring)
    return _to_bot_lookup_schema(monitoring)


@router.post("/bot-monitoring/change-link", response_model=InternalBotLookupResponse)
def bot_change_link(payload: InternalBotCommandRequest, db: Session = Depends(get_db)) -> InternalBotLookupResponse:
    monitoring = _resolve_user_monitoring(db, telegram_id=payload.telegram_id, bot_id=payload.bot_id)
    cleaned_url = (payload.url or "").strip()
    if not cleaned_url:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="URL обязателен")
    monitoring.url = cleaned_url
    monitoring.link_configured = True
    db.commit()
    db.refresh(monitoring)
    return _to_bot_lookup_schema(monitoring)


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
        monitoring = db.get(Monitoring, n.monitoring_id)
        item = db.get(MonitoringItem, n.item_id)
        if not user:
            continue
        if not monitoring or monitoring.bot_id is None:
            continue
        bot = db.get(TelegramBot, monitoring.bot_id)
        out.append(
            InternalNotificationResponse(
                id=n.id,
                telegram_id=user.telegram_id,
                bot_id=monitoring.bot_id,
                telegram_bot_id=bot.telegram_bot_id if bot else None,
                monitoring_id=n.monitoring_id,
                message=n.message,
                photo_url=extract_item_photo_url(item.raw_json if item else None),
            )
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
