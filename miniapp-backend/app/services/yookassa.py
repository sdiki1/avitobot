from __future__ import annotations

import base64
import json
from typing import Any
from urllib import error as urllib_error
from urllib import request as urllib_request
from urllib.parse import quote
from uuid import uuid4

from app.config import settings

YOOKASSA_API_BASE = "https://api.yookassa.ru/v3"


class YooKassaError(RuntimeError):
    pass


def yookassa_is_configured() -> bool:
    return bool(str(settings.yookassa_shop_id or "").strip() and str(settings.yookassa_secret_key or "").strip())


def _auth_header() -> str:
    raw = f"{settings.yookassa_shop_id}:{settings.yookassa_secret_key}".encode("utf-8")
    encoded = base64.b64encode(raw).decode("ascii")
    return f"Basic {encoded}"


def _request_json(
    method: str,
    path: str,
    *,
    payload: dict[str, Any] | None = None,
    idempotence_key: str | None = None,
) -> dict[str, Any]:
    if not yookassa_is_configured():
        raise YooKassaError("ЮKassa не настроена")

    headers = {
        "Authorization": _auth_header(),
        "Content-Type": "application/json",
        "Accept": "application/json",
    }
    if idempotence_key:
        headers["Idempotence-Key"] = idempotence_key

    data = None
    if payload is not None:
        data = json.dumps(payload, ensure_ascii=False, separators=(",", ":")).encode("utf-8")

    req = urllib_request.Request(
        url=f"{YOOKASSA_API_BASE}{path}",
        data=data,
        headers=headers,
        method=method.upper(),
    )
    try:
        with urllib_request.urlopen(req, timeout=30) as response:
            body = response.read().decode("utf-8") if response else ""
            parsed = json.loads(body) if body else {}
            if isinstance(parsed, dict):
                return parsed
            raise YooKassaError("Некорректный ответ ЮKassa")
    except urllib_error.HTTPError as exc:
        raw = exc.read().decode("utf-8", errors="ignore") if hasattr(exc, "read") else ""
        detail = raw or str(exc)
        try:
            parsed = json.loads(raw) if raw else {}
            if isinstance(parsed, dict):
                detail = str(parsed.get("description") or parsed.get("type") or detail)
        except Exception:
            pass
        raise YooKassaError(detail) from exc
    except urllib_error.URLError as exc:
        reason = getattr(exc, "reason", exc)
        raise YooKassaError(f"Ошибка сети ЮKassa: {reason}") from exc


def create_sbp_payment(
    *,
    amount_rub: int,
    description: str,
    return_url: str,
    metadata: dict[str, str] | None = None,
    idempotence_key: str | None = None,
) -> dict[str, Any]:
    amount = max(0, int(amount_rub))
    payload = {
        "amount": {
            "value": f"{amount}.00",
            "currency": "RUB",
        },
        "capture": True,
        "description": (description or "Оплата подписки")[:128],
        "payment_method_data": {"type": "sbp"},
        "confirmation": {
            "type": "redirect",
            "return_url": return_url,
        },
        "metadata": metadata or {},
    }
    return _request_json(
        "POST",
        "/payments",
        payload=payload,
        idempotence_key=idempotence_key or uuid4().hex,
    )


def get_payment(payment_external_id: str) -> dict[str, Any]:
    payment_id = str(payment_external_id or "").strip()
    if not payment_id:
        raise YooKassaError("Пустой идентификатор платежа")
    safe_id = quote(payment_id, safe="")
    return _request_json("GET", f"/payments/{safe_id}")
