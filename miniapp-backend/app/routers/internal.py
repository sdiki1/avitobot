from datetime import timedelta

from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy import and_, or_, select, update
from sqlalchemy.orm import Session

from app.config import settings
from app.database import get_db
from app.models import Monitoring, MonitoringItem, Notification, ProxyConfig, TelegramBot, User, UserSubscription
from app.schemas import (
    InternalBotCommandRequest,
    InternalBotConfigResponse,
    InternalBotLookupResponse,
    InternalBotSyncRequest,
    InternalNotificationResponse,
    InternalNotificationsSentBatchRequest,
    InternalProxyBlockedRequest,
    InternalScanPayload,
)
from app.services.auth import require_internal_token
from app.services.helpers import (
    extract_item_description,
    extract_item_photo_url,
    format_new_item_message,
    format_price_change_message,
    get_active_subscription_query,
    normalize_monitoring_url,
    normalize_proxy_url,
    now_utc,
)
from app.services.notification_queue import enqueue_notification, purge_monitoring_notifications

router = APIRouter(prefix="/internal", tags=["internal"], dependencies=[Depends(require_internal_token)])


def _to_bot_lookup_schema(monitoring: Monitoring) -> InternalBotLookupResponse:
    return InternalBotLookupResponse(
        monitoring_id=monitoring.id,
        title=monitoring.title,
        url=normalize_monitoring_url(monitoring.url),
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


def _clear_monitoring_notifications(db: Session, monitoring: Monitoring) -> tuple[int, int]:
    sent_at = now_utc()
    pending_result = db.execute(
        update(Notification)
        .where(
            and_(
                Notification.monitoring_id == monitoring.id,
                Notification.status == "pending",
            )
        )
        .values(
            status="sent",
            sent_at=sent_at,
        )
    )
    cleared_pending = int(pending_result.rowcount or 0)
    cleared_queue = 0
    if monitoring.bot_id:
        cleared_queue = int(purge_monitoring_notifications(int(monitoring.bot_id), int(monitoring.id)) or 0)
    return cleared_pending, cleared_queue


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


@router.post("/proxies/blocked")
def mark_proxy_blocked(payload: InternalProxyBlockedRequest, db: Session = Depends(get_db)) -> dict:
    raw_proxy = (payload.proxy_url or "").strip()
    if not raw_proxy:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="proxy_url is required")

    normalized_proxy = normalize_proxy_url(raw_proxy)
    proxy = db.scalar(select(ProxyConfig).where(ProxyConfig.proxy_url == raw_proxy))
    if not proxy and normalized_proxy != raw_proxy:
        proxy = db.scalar(select(ProxyConfig).where(ProxyConfig.proxy_url == normalized_proxy))
    if not proxy:
        all_proxies = db.scalars(select(ProxyConfig)).all()
        for candidate in all_proxies:
            if normalize_proxy_url(candidate.proxy_url) == normalized_proxy:
                proxy = candidate
                break

    if not proxy:
        return {"ok": False, "updated": False, "reason": "proxy not found"}

    now = now_utc()
    cooldown_seconds = max(1, int(settings.proxy_block_cooldown_total_seconds))
    proxy.cooldown_until = now + timedelta(seconds=cooldown_seconds)
    proxy.last_blocked_at = now
    proxy.last_block_status = payload.status_code
    proxy.fail_count = int(proxy.fail_count or 0) + 1
    db.commit()
    return {"ok": True, "updated": True, "proxy_id": proxy.id, "cooldown_until": proxy.cooldown_until}


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
    now = now_utc()
    proxies = db.scalars(
        select(ProxyConfig)
        .where(
            and_(
                ProxyConfig.is_active.is_(True),
                or_(ProxyConfig.cooldown_until.is_(None), ProxyConfig.cooldown_until <= now),
                ProxyConfig.name.notlike("env-proxy-%"),
            )
        )
        .order_by(ProxyConfig.id.asc())
    ).all()

    payload = []
    active_proxy_urls = [proxy.proxy_url for proxy in proxies if proxy.proxy_url]
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
        proxy_pool: list[str] = []
        proxy_url = None
        if active_proxy_urls:
            first_idx = mon.id % len(active_proxy_urls)
            proxy_pool = active_proxy_urls[first_idx:] + active_proxy_urls[:first_idx]
            proxy_url = proxy_pool[0]

        payload.append(
            {
                "monitoring_id": mon.id,
                "telegram_id": user.telegram_id,
                "url": normalize_monitoring_url(mon.url),
                "title": mon.title,
                "keywords_white": [x for x in (mon.keywords_white or "").split(",") if x],
                "keywords_black": [x for x in (mon.keywords_black or "").split(",") if x],
                "min_price": mon.min_price,
                "max_price": mon.max_price,
                "geo": mon.geo,
                "proxy_url": proxy_url,
                "proxy_pool": proxy_pool,
            }
        )
    return payload


@router.post("/monitorings/{monitoring_id}/scan-result")
def save_scan_result(monitoring_id: int, payload: InternalScanPayload, db: Session = Depends(get_db)) -> dict:
    monitoring = db.get(Monitoring, monitoring_id)
    if not monitoring:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Monitoring not found")
    now = now_utc()
    if not monitoring.is_active:
        monitoring.last_checked_at = now
        db.commit()
        return {"ok": True, "created_items": 0, "updated_items": 0, "price_changes": 0, "enqueued": 0}

    user = db.get(User, monitoring.user_id)
    if not user or monitoring.bot_id is None:
        monitoring.last_checked_at = now
        db.commit()
        return {"ok": True, "created_items": 0, "updated_items": 0, "price_changes": 0, "enqueued": 0}

    notify_since_at = monitoring.notify_since_at

    created = 0
    touched = 0
    price_changes = 0
    queue_payloads: list[dict] = []
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
            price_decreased = (
                old_price is not None
                and new_price is not None
                and new_price < old_price
            )

            existing.title = item.title
            existing.url = item.url
            existing.price_rub = item.price_rub
            existing.location = item.location
            existing.published_at = item.published_at
            existing.raw_json = item.raw_json
            existing.last_seen_at = now_utc()

            if price_decreased and monitoring.notify_price_drop:
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
                        include_description=monitoring.include_description,
                        include_seller_info=monitoring.include_seller_info,
                    ),
                    status="pending",
                )
                db.add(notification)
                db.flush()
                queue_payloads.append(
                    {
                        "id": notification.id,
                        "telegram_id": user.telegram_id,
                        "bot_id": monitoring.bot_id,
                        "monitoring_id": monitoring.id,
                        "monitoring_url": normalize_monitoring_url(monitoring.url),
                        "message": notification.message,
                        "photo_url": extract_item_photo_url(existing.raw_json) if monitoring.include_photo else None,
                    }
                )
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

        should_notify_new_item = True
        if notify_since_at is not None:
            published_at = db_item.published_at
            if published_at is None or published_at <= notify_since_at:
                should_notify_new_item = False

        if should_notify_new_item:
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
                    include_description=monitoring.include_description,
                    include_seller_info=monitoring.include_seller_info,
                ),
                status="pending",
            )
            db.add(notification)
            db.flush()
            queue_payloads.append(
                {
                    "id": notification.id,
                    "telegram_id": user.telegram_id,
                    "bot_id": monitoring.bot_id,
                    "monitoring_id": monitoring.id,
                    "monitoring_url": normalize_monitoring_url(monitoring.url),
                    "message": notification.message,
                    "photo_url": extract_item_photo_url(db_item.raw_json) if monitoring.include_photo else None,
                }
            )
        created += 1

    monitoring.last_checked_at = now
    db.commit()

    enqueued = 0
    for payload_item in queue_payloads:
        if enqueue_notification(int(monitoring.bot_id), payload_item):
            enqueued += 1

    return {
        "ok": True,
        "created_items": created,
        "updated_items": touched,
        "price_changes": price_changes,
        "enqueued": enqueued,
    }


@router.get("/bot-monitoring/current", response_model=InternalBotLookupResponse)
def bot_current_monitoring(
    telegram_id: int = Query(...),
    bot_id: int = Query(...),
    db: Session = Depends(get_db),
) -> InternalBotLookupResponse:
    monitoring = _resolve_user_monitoring(db, telegram_id=telegram_id, bot_id=bot_id)
    return _to_bot_lookup_schema(monitoring)


@router.get("/monitorings/{monitoring_id}/state")
def monitoring_state(monitoring_id: int, db: Session = Depends(get_db)) -> dict:
    monitoring = db.get(Monitoring, monitoring_id)
    if not monitoring:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Monitoring not found")
    user = db.get(User, monitoring.user_id)
    return {
        "monitoring_id": monitoring.id,
        "is_active": bool(monitoring.is_active),
        "link_configured": bool(monitoring.link_configured),
        "telegram_id": user.telegram_id if user else None,
        "bot_id": monitoring.bot_id,
    }


@router.post("/bot-monitoring/start", response_model=InternalBotLookupResponse)
def bot_start_monitoring(payload: InternalBotCommandRequest, db: Session = Depends(get_db)) -> InternalBotLookupResponse:
    monitoring = _resolve_user_monitoring(db, telegram_id=payload.telegram_id, bot_id=payload.bot_id)
    _require_active_subscription(db, monitoring.user_id)
    if not monitoring.link_configured:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Сначала задайте ссылку командой /change_link https://www.avito.ru/...",
        )
    _clear_monitoring_notifications(db, monitoring)
    monitoring.is_active = True
    monitoring.notify_since_at = now_utc()
    db.commit()
    db.refresh(monitoring)
    return _to_bot_lookup_schema(monitoring)


@router.post("/bot-monitoring/stop", response_model=InternalBotLookupResponse)
def bot_stop_monitoring(payload: InternalBotCommandRequest, db: Session = Depends(get_db)) -> InternalBotLookupResponse:
    monitoring = _resolve_user_monitoring(db, telegram_id=payload.telegram_id, bot_id=payload.bot_id)
    _clear_monitoring_notifications(db, monitoring)
    monitoring.is_active = False
    db.commit()
    db.refresh(monitoring)
    return _to_bot_lookup_schema(monitoring)


@router.post("/bot-monitoring/change-link", response_model=InternalBotLookupResponse)
def bot_change_link(payload: InternalBotCommandRequest, db: Session = Depends(get_db)) -> InternalBotLookupResponse:
    monitoring = _resolve_user_monitoring(db, telegram_id=payload.telegram_id, bot_id=payload.bot_id)
    cleaned_url = normalize_monitoring_url(payload.url)
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
                monitoring_url=normalize_monitoring_url(monitoring.url),
                message=n.message,
                photo_url=extract_item_photo_url(item.raw_json if item else None) if monitoring.include_photo else None,
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


@router.post("/notifications/sent-batch")
def mark_sent_batch(payload: InternalNotificationsSentBatchRequest, db: Session = Depends(get_db)) -> dict:
    ids = sorted({int(notification_id) for notification_id in (payload.notification_ids or []) if int(notification_id) > 0})
    if not ids:
        return {"ok": True, "updated": 0}

    sent_at = now_utc()
    result = db.execute(
        update(Notification)
        .where(Notification.id.in_(ids))
        .values(
            status="sent",
            sent_at=sent_at,
        )
    )
    db.commit()
    return {"ok": True, "updated": int(result.rowcount or 0)}
