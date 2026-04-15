from __future__ import annotations

import json
import logging
from typing import Any

from redis import Redis

from app.config import settings

logger = logging.getLogger(__name__)

_redis_client: Redis | None = None


def _client() -> Redis:
    global _redis_client
    if _redis_client is None:
        _redis_client = Redis.from_url(settings.redis_url, decode_responses=True)
    return _redis_client


def queue_key_for_bot(bot_id: int) -> str:
    return f"{settings.redis_notify_queue_prefix}{int(bot_id)}"


def enqueue_notification(bot_id: int, payload: dict[str, Any]) -> bool:
    if int(bot_id) <= 0:
        return False
    try:
        key = queue_key_for_bot(int(bot_id))
        _client().rpush(key, json.dumps(payload, ensure_ascii=False, separators=(",", ":")))
        return True
    except Exception as exc:
        logger.warning("Failed to enqueue redis notification bot_id=%s error=%s", bot_id, exc)
        return False
