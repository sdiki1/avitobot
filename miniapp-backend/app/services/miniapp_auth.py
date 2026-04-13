from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime
import hashlib
import hmac
import json
import time
from urllib.parse import parse_qsl

import jwt
from fastapi import Depends, HTTPException, Request, Response, status
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.config import settings
from app.database import get_db
from app.models import TelegramBot, User
from app.services.helpers import ensure_user_referral_code


@dataclass(frozen=True)
class MiniAppIdentity:
    telegram_id: int
    username: str | None
    full_name: str | None


def _unauthorized(detail: str = "Unauthorized") -> HTTPException:
    return HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail=detail)


def _token_is_placeholder(token: str) -> bool:
    return token.startswith("change_me_")


def _cookie_samesite() -> str:
    candidate = str(settings.miniapp_auth_cookie_samesite or "lax").lower()
    if candidate in {"lax", "strict", "none"}:
        return candidate
    return "lax"


def _sign_init_data(data_check_string: str, bot_token: str) -> str:
    secret_key = hmac.new(b"WebAppData", bot_token.encode("utf-8"), hashlib.sha256).digest()
    return hmac.new(secret_key, data_check_string.encode("utf-8"), hashlib.sha256).hexdigest()


def get_active_bot_tokens(db: Session) -> list[str]:
    tokens = [
        token.strip()
        for token in db.scalars(select(TelegramBot.bot_token).where(TelegramBot.is_active.is_(True))).all()
        if token and token.strip()
    ]

    fallback = (settings.default_bot_token or "").strip()
    if fallback and fallback not in tokens:
        tokens.append(fallback)

    return [token for token in tokens if not _token_is_placeholder(token)]


def parse_and_validate_init_data(init_data: str, bot_tokens: list[str]) -> MiniAppIdentity:
    if not init_data:
        raise _unauthorized("initData is required")
    if not bot_tokens:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="No active bot tokens configured for Mini App authentication",
        )

    parsed_pairs = dict(parse_qsl(init_data, keep_blank_values=True))
    received_hash = parsed_pairs.pop("hash", None)
    if not received_hash:
        raise _unauthorized("Invalid initData hash")

    auth_date_raw = parsed_pairs.get("auth_date")
    if not auth_date_raw or not auth_date_raw.isdigit():
        raise _unauthorized("Invalid initData auth_date")

    age_seconds = int(time.time()) - int(auth_date_raw)
    if settings.miniapp_initdata_ttl_sec > 0 and age_seconds > settings.miniapp_initdata_ttl_sec:
        raise _unauthorized("initData has expired")

    data_check_string = "\n".join(f"{key}={value}" for key, value in sorted(parsed_pairs.items()))
    valid_hash = any(hmac.compare_digest(received_hash, _sign_init_data(data_check_string, token)) for token in bot_tokens)
    if not valid_hash:
        raise _unauthorized("initData signature mismatch")

    user_raw = parsed_pairs.get("user")
    if not user_raw:
        raise _unauthorized("initData does not contain user")

    try:
        user_data = json.loads(user_raw)
    except json.JSONDecodeError as exc:
        raise _unauthorized("initData user payload is invalid") from exc

    if not isinstance(user_data, dict):
        raise _unauthorized("initData user payload is invalid")

    telegram_id_raw = user_data.get("id")
    if isinstance(telegram_id_raw, str):
        if not telegram_id_raw.isdigit():
            raise _unauthorized("Invalid Telegram user id")
        telegram_id = int(telegram_id_raw)
    elif isinstance(telegram_id_raw, int):
        telegram_id = telegram_id_raw
    else:
        raise _unauthorized("Invalid Telegram user id")

    username = user_data.get("username")
    if not isinstance(username, str) or not username.strip():
        username = None

    first_name = user_data.get("first_name")
    last_name = user_data.get("last_name")
    names = [x.strip() for x in [first_name, last_name] if isinstance(x, str) and x.strip()]
    full_name = " ".join(names) if names else None

    return MiniAppIdentity(telegram_id=telegram_id, username=username, full_name=full_name)


def _build_jwt_token(telegram_id: int, secret: str, ttl_sec: int, token_type: str) -> str:
    now_ts = int(datetime.now(UTC).timestamp())
    payload = {
        "sub": str(telegram_id),
        "telegram_id": telegram_id,
        "token_type": token_type,
        "iat": now_ts,
        "exp": now_ts + max(1, int(ttl_sec)),
    }
    return jwt.encode(payload, secret, algorithm="HS256")


def issue_miniapp_session(response: Response, telegram_id: int) -> None:
    access_token = _build_jwt_token(
        telegram_id=telegram_id,
        secret=settings.miniapp_access_token_secret,
        ttl_sec=settings.miniapp_access_ttl_sec,
        token_type="access",
    )
    refresh_token = _build_jwt_token(
        telegram_id=telegram_id,
        secret=settings.miniapp_refresh_token_secret,
        ttl_sec=settings.miniapp_refresh_ttl_sec,
        token_type="refresh",
    )

    cookie_kwargs = {
        "httponly": True,
        "secure": settings.miniapp_auth_cookie_secure,
        "samesite": _cookie_samesite(),
        "path": "/",
    }
    response.set_cookie(
        settings.miniapp_access_cookie_name,
        access_token,
        max_age=max(1, int(settings.miniapp_access_ttl_sec)),
        **cookie_kwargs,
    )
    response.set_cookie(
        settings.miniapp_refresh_cookie_name,
        refresh_token,
        max_age=max(1, int(settings.miniapp_refresh_ttl_sec)),
        **cookie_kwargs,
    )


def clear_miniapp_session(response: Response) -> None:
    response.delete_cookie(settings.miniapp_access_cookie_name, path="/")
    response.delete_cookie(settings.miniapp_refresh_cookie_name, path="/")


def _extract_telegram_id(token: str, secret: str, token_type: str) -> int | None:
    if not token:
        return None

    try:
        payload = jwt.decode(token, secret, algorithms=["HS256"])
    except jwt.PyJWTError:
        return None

    if payload.get("token_type") != token_type:
        return None

    telegram_id_raw = payload.get("telegram_id")
    if isinstance(telegram_id_raw, str):
        if not telegram_id_raw.isdigit():
            return None
        return int(telegram_id_raw)
    if isinstance(telegram_id_raw, int):
        return telegram_id_raw
    return None


def resolve_telegram_id_from_cookies(request: Request, response: Response) -> int:
    access_token = request.cookies.get(settings.miniapp_access_cookie_name, "")
    telegram_id = _extract_telegram_id(access_token, settings.miniapp_access_token_secret, "access")
    if telegram_id is not None:
        return telegram_id

    refresh_token = request.cookies.get(settings.miniapp_refresh_cookie_name, "")
    telegram_id = _extract_telegram_id(refresh_token, settings.miniapp_refresh_token_secret, "refresh")
    if telegram_id is None:
        raise _unauthorized("Mini App session is missing or expired")

    issue_miniapp_session(response, telegram_id)
    return telegram_id


def require_miniapp_user(
    request: Request,
    response: Response,
    db: Session = Depends(get_db),
) -> User:
    telegram_id = resolve_telegram_id_from_cookies(request, response)
    user = db.scalar(select(User).where(User.telegram_id == telegram_id))
    if not user:
        raise _unauthorized("User not found for current Mini App session")
    return ensure_user_referral_code(db, user)


def assert_telegram_id_match(auth_user: User, telegram_id: int) -> None:
    if int(auth_user.telegram_id) != int(telegram_id):
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="telegram_id does not match auth session")
