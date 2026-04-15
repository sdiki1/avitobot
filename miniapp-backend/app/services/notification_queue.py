from __future__ import annotations

import json
import logging
from typing import Any
from uuid import uuid4

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


def purge_monitoring_notifications(bot_id: int, monitoring_id: int) -> int:
    if int(bot_id) <= 0 or int(monitoring_id) <= 0:
        return 0

    redis_client = _client()
    queue_key = queue_key_for_bot(int(bot_id))
    temp_key = f"{queue_key}:purge:{int(monitoring_id)}:{uuid4().hex}"
    dropped = 0

    try:
        initial_len = int(redis_client.llen(queue_key) or 0)
        if initial_len <= 0:
            return 0

        for _ in range(initial_len):
            raw_payload = redis_client.lpop(queue_key)
            if raw_payload is None:
                break
            try:
                payload = json.loads(raw_payload)
            except Exception:
                continue

            payload_monitoring_id = int(payload.get("monitoring_id") or 0)
            if payload_monitoring_id == int(monitoring_id):
                dropped += 1
                continue

            redis_client.rpush(temp_key, raw_payload)

        while True:
            moved = redis_client.rpoplpush(temp_key, queue_key)
            if moved is None:
                break
    except Exception as exc:
        logger.warning(
            "Failed to purge redis notifications bot_id=%s monitoring_id=%s error=%s",
            bot_id,
            monitoring_id,
            exc,
        )
    finally:
        try:
            redis_client.delete(temp_key)
        except Exception:
            pass

    return dropped
