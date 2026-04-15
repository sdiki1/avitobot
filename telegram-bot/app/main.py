from __future__ import annotations

import asyncio
from collections import deque
from datetime import datetime, timedelta, timezone
import os
import re
from contextlib import suppress
from dataclasses import dataclass
from typing import Any
from urllib.parse import urlsplit

import httpx
from aiogram import Bot, Dispatcher, F, Router
from aiogram.filters import Command, CommandStart
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup
from aiogram.exceptions import TelegramRetryAfter
from aiogram.types import (
    BufferedInputFile,
    BotCommand,
    KeyboardButton,
    Message,
    ReplyKeyboardMarkup,
    WebAppInfo,
)
from aiogram.utils.token import TokenValidationError, validate_token
from loguru import logger


BACKEND_URL = os.getenv("BACKEND_URL", "http://localhost:8001").rstrip("/")
INTERNAL_API_TOKEN = os.getenv("INTERNAL_API_TOKEN", "change_me_internal_token")
MINIAPP_PUBLIC_URL = os.getenv("MINIAPP_PUBLIC_URL", "http://localhost")
BOTS_REFRESH_SEC = int(os.getenv("BOTS_REFRESH_SEC", "15"))
NOTIFY_POLL_SEC = float(os.getenv("NOTIFY_POLL_SEC", "1"))
NOTIFY_BACKLOG_POLL_SEC = float(os.getenv("NOTIFY_BACKLOG_POLL_SEC", "0.2"))
NOTIFY_FETCH_LIMIT = int(os.getenv("NOTIFY_FETCH_LIMIT", "300"))
NOTIFY_SEND_CONCURRENCY = int(os.getenv("NOTIFY_SEND_CONCURRENCY", "8"))
PHOTO_RETRY_ATTEMPTS = int(os.getenv("PHOTO_RETRY_ATTEMPTS", "3"))
PHOTO_RETRY_BASE_DELAY_SEC = float(os.getenv("PHOTO_RETRY_BASE_DELAY_SEC", "1.5"))
PHOTO_DOWNLOAD_TIMEOUT_SEC = float(os.getenv("PHOTO_DOWNLOAD_TIMEOUT_SEC", "12"))
RATE_LIMIT_ALERT_COOLDOWN_SEC = int(os.getenv("RATE_LIMIT_ALERT_COOLDOWN_SEC", "900"))
MONITORING_BURST_WINDOW_SEC = float(os.getenv("MONITORING_BURST_WINDOW_SEC", "30"))
MONITORING_BURST_MAX_MESSAGES = int(os.getenv("MONITORING_BURST_MAX_MESSAGES", "10"))
MONITORING_BURST_ALERT_COOLDOWN_SEC = int(os.getenv("MONITORING_BURST_ALERT_COOLDOWN_SEC", "120"))

BTN_START_MONITORING = "▶️ Запустить мониторинг"
BTN_STOP_MONITORING = "⏹ Остановить мониторинг"
BTN_STATUS = "📊 Статус"
BTN_CHANGE_LINK = "🔗 Поменять ссылку"
BTN_OPEN_MINIAPP = "📱 Открыть MiniApp"
BTN_CANCEL_CHANGE = "✖️ Отмена изменения"


def has_valid_bot_token(token: str) -> bool:
    if not token:
        return False
    try:
        validate_token(token)
    except TokenValidationError:
        return False
    return True


def build_miniapp_url(telegram_id: int) -> str:
    _ = telegram_id
    return MINIAPP_PUBLIC_URL


def miniapp_keyboard(telegram_id: int) -> ReplyKeyboardMarkup:
    return ReplyKeyboardMarkup(
        keyboard=[
            [KeyboardButton(text=BTN_OPEN_MINIAPP, web_app=WebAppInfo(url=build_miniapp_url(telegram_id)))],
        ],
        resize_keyboard=True,
        one_time_keyboard=True,
        input_field_placeholder="Открыть MiniApp",
    )


def monitoring_actions_keyboard(telegram_id: int, include_cancel: bool = False) -> ReplyKeyboardMarkup:
    rows: list[list[KeyboardButton]] = []
    if include_cancel:
        rows.append([KeyboardButton(text=BTN_CANCEL_CHANGE)])
    rows.extend(
        [
            [KeyboardButton(text=BTN_START_MONITORING), KeyboardButton(text=BTN_STOP_MONITORING)],
            [KeyboardButton(text=BTN_STATUS), KeyboardButton(text=BTN_CHANGE_LINK)],
            [KeyboardButton(text=BTN_OPEN_MINIAPP, web_app=WebAppInfo(url=build_miniapp_url(telegram_id)))],
        ]
    )
    return ReplyKeyboardMarkup(
        keyboard=rows,
        resize_keyboard=True,
        input_field_placeholder="Выберите действие",
    )


class LinkChangeState(StatesGroup):
    waiting_url = State()


def _response_json(response: httpx.Response) -> dict[str, Any]:
    try:
        payload = response.json()
        if isinstance(payload, dict):
            return payload
    except Exception:
        pass
    return {"detail": response.text}


def _extract_error(payload: dict[str, Any]) -> str:
    detail = payload.get("detail")
    if isinstance(detail, str):
        return detail
    if detail:
        return str(detail)
    return "Неизвестная ошибка"


def _format_monitoring_status(monitoring: dict[str, Any]) -> str:
    state = "включен" if monitoring.get("is_active") else "остановлен"
    link_configured = "да" if monitoring.get("link_configured") else "нет"
    title = monitoring.get("title") or f"#{monitoring.get('monitoring_id')}"
    return (
        f"Мониторинг: {title}\n"
        f"Статус: {state}\n"
        f"Ссылка задана: {link_configured}\n"
        f"Текущая ссылка: {monitoring.get('url')}"
    )


def _format_datetime_ru(value: str | None) -> str:
    if not value:
        return "—"
    try:
        normalized = value.replace("Z", "+00:00")
        dt = datetime.fromisoformat(normalized)
        return dt.strftime("%d.%m.%Y %H:%M")
    except Exception:
        return value


def _extract_start_arg(text: str | None) -> str:
    parts = (text or "").split(maxsplit=1)
    if len(parts) < 2:
        return ""
    return parts[1].strip().lower()


def _extract_referral_code(start_arg: str) -> str | None:
    value = (start_arg or "").strip().lower()
    if not value.startswith("ref_"):
        return None
    if not re.fullmatch(r"ref_[a-z0-9_]+", value):
        return None
    return value


def _looks_like_url(value: str) -> bool:
    lowered = value.lower()
    return lowered.startswith("http://") or lowered.startswith("https://")


def _fit_photo_caption(value: str, max_len: int = 1024) -> str:
    text = (value or "").strip()
    if len(text) <= max_len:
        return text
    plain_text = re.sub(r"</?[^>]+>", "", text)
    plain_text = " ".join(plain_text.split()).strip()
    if len(plain_text) <= max_len:
        return plain_text
    return f"{plain_text[: max_len - 1]}…"


async def _pin_monitoring_link(bot: Bot, chat_id: int, monitoring_url: str) -> None:
    link = str(monitoring_url or "").strip()
    if not link:
        return
    try:
        message = await bot.send_message(
            chat_id=chat_id,
            text=f"📌 Активная ссылка мониторинга:\n{link}",
            disable_web_page_preview=True,
        )
        with suppress(Exception):
            await bot.pin_chat_message(
                chat_id=chat_id,
                message_id=message.message_id,
                disable_notification=True,
            )
    except Exception as exc:
        logger.warning("Failed to pin monitoring link chat_id={} url={} error={}", chat_id, link, exc)


def _is_retryable_photo_error(exc: Exception) -> bool:
    text = str(exc).lower()
    retryable_markers = (
        "failed to get http url content",
        "wrong type of the web page content",
        "wrong file identifier/http url specified",
        "timed out",
        "timeout",
        "temporarily unavailable",
    )
    return any(marker in text for marker in retryable_markers)


async def _send_photo_with_retry(
    bot: Bot,
    chat_id: int,
    photo_url: str,
    caption: str | None = None,
    parse_mode: str | None = None,
) -> None:
    attempts = max(1, PHOTO_RETRY_ATTEMPTS)
    last_exc: Exception | None = None

    for attempt in range(1, attempts + 1):
        try:
            payload = {
                "chat_id": chat_id,
                "photo": photo_url,
            }
            if caption is not None:
                payload["caption"] = caption
            if parse_mode is not None:
                payload["parse_mode"] = parse_mode
            await bot.send_photo(**payload)
            return
        except Exception as exc:
            last_exc = exc
            if attempt >= attempts or not _is_retryable_photo_error(exc):
                raise

            delay = max(0.2, PHOTO_RETRY_BASE_DELAY_SEC) * attempt
            logger.warning(
                "send_photo retry {}/{} chat_id={} url={} after error: {}",
                attempt,
                attempts,
                chat_id,
                photo_url,
                exc,
            )
            await asyncio.sleep(delay)

    if last_exc is not None:
        raise last_exc


def _guess_extension_from_content_type(content_type: str) -> str:
    ct = (content_type or "").lower()
    if "png" in ct:
        return "png"
    if "webp" in ct:
        return "webp"
    if "gif" in ct:
        return "gif"
    return "jpg"


def _guess_extension_from_bytes(data: bytes) -> str:
    if data.startswith(b"\x89PNG\r\n\x1a\n"):
        return "png"
    if data.startswith(b"GIF87a") or data.startswith(b"GIF89a"):
        return "gif"
    if data[:4] == b"RIFF" and data[8:12] == b"WEBP":
        return "webp"
    return "jpg"


def _build_photo_filename(photo_url: str, content_type: str, data: bytes) -> str:
    path = urlsplit(photo_url).path or ""
    basename = path.rsplit("/", 1)[-1].strip()
    ext = _guess_extension_from_content_type(content_type)
    if "." not in basename:
        return f"photo.{ext}"
    return basename


async def _download_photo_bytes(photo_url: str) -> tuple[bytes, str] | None:
    candidates = [photo_url]
    if "?" in photo_url:
        candidates.append(photo_url.split("?", 1)[0])

    headers = {
        "User-Agent": (
            "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
            "AppleWebKit/537.36 (KHTML, like Gecko) "
            "Chrome/126.0.0.0 Safari/537.36"
        ),
        "Accept": "image/avif,image/webp,image/apng,image/*,*/*;q=0.8",
        "Referer": "https://www.avito.ru/",
    }

    timeout = max(2.0, PHOTO_DOWNLOAD_TIMEOUT_SEC)
    async with httpx.AsyncClient(timeout=timeout, follow_redirects=True, headers=headers) as client:
        for candidate in candidates:
            try:
                response = await client.get(candidate)
                if response.status_code >= 400:
                    continue
                data = response.content or b""
                if not data:
                    continue
                if len(data) > 10 * 1024 * 1024:
                    continue

                content_type = response.headers.get("content-type", "")
                if "image/" not in content_type.lower():
                    guessed = _guess_extension_from_bytes(data)
                    if guessed not in {"jpg", "png", "webp", "gif"}:
                        continue
                    filename = f"photo.{guessed}"
                    return data, filename

                filename = _build_photo_filename(candidate, content_type, data)
                return data, filename
            except Exception:
                continue

    return None


async def _send_downloaded_photo_with_retry(
    bot: Bot,
    chat_id: int,
    photo_data: bytes,
    filename: str,
    caption: str | None = None,
    parse_mode: str | None = None,
) -> None:
    attempts = max(1, PHOTO_RETRY_ATTEMPTS)
    last_exc: Exception | None = None

    for attempt in range(1, attempts + 1):
        try:
            payload = {
                "chat_id": chat_id,
                "photo": BufferedInputFile(photo_data, filename=filename or "photo.jpg"),
            }
            if caption is not None:
                payload["caption"] = caption
            if parse_mode is not None:
                payload["parse_mode"] = parse_mode
            await bot.send_photo(**payload)
            return
        except Exception as exc:
            last_exc = exc
            if attempt >= attempts:
                raise
            delay = max(0.2, PHOTO_RETRY_BASE_DELAY_SEC) * attempt
            await asyncio.sleep(delay)

    if last_exc is not None:
        raise last_exc


def _format_plan_line(plan: dict[str, Any]) -> str:
    name = str(plan.get("name") or "Тариф")
    price = plan.get("price_rub")
    links_limit = plan.get("links_limit")
    duration_days = plan.get("duration_days")
    base = f"• {name}: {price}₽ | {links_limit} мониторингов | {duration_days} дней"
    description = str(plan.get("description") or "").strip()
    if description:
        return f"{base}\n{description}"
    return base


def _build_plans_message(plans: list[dict[str, Any]]) -> str:
    if not plans:
        return "Тарифы пока не настроены в админ-панели."
    lines = ["Доступные тарифы:"]
    for plan in plans:
        lines.append(_format_plan_line(plan))
    lines.append("\nОформить подписку можно в MiniApp.")
    return "\n".join(lines)


def _is_telegram_rate_limit_error(exc: Exception) -> bool:
    if isinstance(exc, TelegramRetryAfter):
        return True
    text = str(exc).lower()
    return "too many requests" in text or "retry after" in text or "flood control" in text


def _rate_limit_warning_text(monitoring_url: str) -> str:
    return (
        "Ссылка слишком активна!\n"
        f"🔗 Ссылка: {monitoring_url}\n\n"
        "🤖 Бот отправляет слишком много объявлений в минуту и упирается в лимиты телеграм.\n"
        "Пожалуйста, используйте ссылки внутри категорий или конкретных городов.\n"
        "Телеграм ограничивает количество сообщений в минуту, поэтому ссылки с большим количеством объявлений "
        "в минуту будут пропускать часть объявлений.\n\n"
        "Это сообщение автоматическое и срабатывает при сильном потоке объявлений. "
        "Если это происходит редко, просто проигнорируйте его."
    )


def _monitoring_burst_warning_text(monitoring_url: str) -> str:
    return (
        "Ссылка слишком активна!\n"
        f"🔗 Ссылка: {monitoring_url}\n\n"
        "За последние 30 секунд найдено слишком много объявлений.\n"
        "Отправлено только первые 10, остальные пропущены.\n\n"
        "Сузьте фильтр: используйте категории, город и ограничения по цене."
    )


async def _maybe_send_rate_limit_warning(
    runtime: "BotRuntime",
    notification: dict[str, Any],
    exc: Exception,
    cooldowns: dict[tuple[int, int, int], datetime],
) -> None:
    if not _is_telegram_rate_limit_error(exc):
        return

    bot_id = int(notification.get("bot_id") or 0)
    chat_id = int(notification.get("telegram_id") or 0)
    monitoring_id = int(notification.get("monitoring_id") or 0)
    key = (bot_id, chat_id, monitoring_id)

    now = datetime.now(timezone.utc)
    cooldown_until = cooldowns.get(key)
    if cooldown_until and now < cooldown_until:
        return

    monitoring_url = str(notification.get("monitoring_url") or "").strip() or "не указана"
    text = _rate_limit_warning_text(monitoring_url)

    try:
        await runtime.bot.send_message(
            chat_id=chat_id,
            text=text,
            disable_web_page_preview=False,
        )
        cooldowns[key] = now + timedelta(seconds=max(60, RATE_LIMIT_ALERT_COOLDOWN_SEC))
    except Exception as warn_exc:
        logger.warning(
            "Failed to send rate-limit warning notification_id={} monitoring_id={} error={}",
            notification.get("id"),
            monitoring_id,
            warn_exc,
        )


async def _maybe_send_monitoring_burst_warning(
    runtime: "BotRuntime",
    notification: dict[str, Any],
    cooldowns: dict[tuple[int, int, int], datetime],
) -> None:
    bot_id = int(notification.get("bot_id") or 0)
    chat_id = int(notification.get("telegram_id") or 0)
    monitoring_id = int(notification.get("monitoring_id") or 0)
    key = (bot_id, chat_id, monitoring_id)

    now = datetime.now(timezone.utc)
    cooldown_until = cooldowns.get(key)
    if cooldown_until and now < cooldown_until:
        return

    monitoring_url = str(notification.get("monitoring_url") or "").strip() or "не указана"
    text = _monitoring_burst_warning_text(monitoring_url)

    try:
        await runtime.bot.send_message(
            chat_id=chat_id,
            text=text,
            disable_web_page_preview=False,
        )
        cooldowns[key] = now + timedelta(
            seconds=max(
                int(max(1.0, MONITORING_BURST_WINDOW_SEC)),
                max(30, MONITORING_BURST_ALERT_COOLDOWN_SEC),
            )
        )
    except Exception as warn_exc:
        logger.warning(
            "Failed to send burst warning notification_id={} monitoring_id={} error={}",
            notification.get("id"),
            monitoring_id,
            warn_exc,
        )


class BackendAPI:
    def __init__(self) -> None:
        self.client = httpx.AsyncClient(timeout=30)

    async def close(self) -> None:
        await self.client.aclose()

    async def auth_user(
        self,
        telegram_id: int,
        username: str | None,
        full_name: str | None,
        referral_code: str | None = None,
    ) -> dict[str, Any]:
        payload = {
            "telegram_id": telegram_id,
            "username": username,
            "full_name": full_name,
            "referral_code": referral_code,
        }
        response = await self.client.post(f"{BACKEND_URL}/api/v1/public/auth/telegram", json=payload)
        response.raise_for_status()
        return response.json()

    async def list_plans(self) -> list[dict[str, Any]]:
        response = await self.client.get(f"{BACKEND_URL}/api/v1/public/plans")
        response.raise_for_status()
        payload = response.json()
        return payload if isinstance(payload, list) else []

    async def get_profile(self, telegram_id: int) -> dict[str, Any]:
        response = await self.client.get(
            f"{BACKEND_URL}/api/v1/public/profile",
            params={"telegram_id": telegram_id},
        )
        response.raise_for_status()
        payload = response.json()
        return payload if isinstance(payload, dict) else {}

    async def onboarding_trial(self, telegram_id: int) -> dict[str, Any]:
        response = await self.client.post(
            f"{BACKEND_URL}/api/v1/public/onboarding-trial",
            json={"telegram_id": telegram_id},
        )
        response.raise_for_status()
        payload = response.json()
        return payload if isinstance(payload, dict) else {}

    async def active_bots(self) -> list[dict[str, Any]]:
        response = await self.client.get(
            f"{BACKEND_URL}/api/v1/internal/bots/active",
            headers={"X-Internal-Token": INTERNAL_API_TOKEN},
        )
        response.raise_for_status()
        payload = response.json()
        return payload if isinstance(payload, list) else []

    async def sync_bot_metadata(self, bot_id: int, telegram_bot_id: int, bot_username: str | None) -> None:
        payload = {
            "telegram_bot_id": telegram_bot_id,
            "bot_username": bot_username,
        }
        response = await self.client.post(
            f"{BACKEND_URL}/api/v1/internal/bots/{bot_id}/sync",
            json=payload,
            headers={"X-Internal-Token": INTERNAL_API_TOKEN},
        )
        response.raise_for_status()

    async def current_monitoring(self, bot_id: int, telegram_id: int) -> tuple[int, dict[str, Any]]:
        response = await self.client.get(
            f"{BACKEND_URL}/api/v1/internal/bot-monitoring/current",
            params={"telegram_id": telegram_id, "bot_id": bot_id},
            headers={"X-Internal-Token": INTERNAL_API_TOKEN},
        )
        return response.status_code, _response_json(response)

    async def start_monitoring(self, bot_id: int, telegram_id: int) -> tuple[int, dict[str, Any]]:
        payload = {"telegram_id": telegram_id, "bot_id": bot_id}
        response = await self.client.post(
            f"{BACKEND_URL}/api/v1/internal/bot-monitoring/start",
            json=payload,
            headers={"X-Internal-Token": INTERNAL_API_TOKEN},
        )
        return response.status_code, _response_json(response)

    async def stop_monitoring(self, bot_id: int, telegram_id: int) -> tuple[int, dict[str, Any]]:
        payload = {"telegram_id": telegram_id, "bot_id": bot_id}
        response = await self.client.post(
            f"{BACKEND_URL}/api/v1/internal/bot-monitoring/stop",
            json=payload,
            headers={"X-Internal-Token": INTERNAL_API_TOKEN},
        )
        return response.status_code, _response_json(response)

    async def change_link(self, bot_id: int, telegram_id: int, url: str) -> tuple[int, dict[str, Any]]:
        payload = {"telegram_id": telegram_id, "bot_id": bot_id, "url": url}
        response = await self.client.post(
            f"{BACKEND_URL}/api/v1/internal/bot-monitoring/change-link",
            json=payload,
            headers={"X-Internal-Token": INTERNAL_API_TOKEN},
        )
        return response.status_code, _response_json(response)

    async def pending_notifications(self, limit: int = 100) -> list[dict[str, Any]]:
        response = await self.client.get(
            f"{BACKEND_URL}/api/v1/internal/notifications/pending",
            params={"limit": limit},
            headers={"X-Internal-Token": INTERNAL_API_TOKEN},
        )
        response.raise_for_status()
        payload = response.json()
        return payload if isinstance(payload, list) else []

    async def mark_notification_sent(self, notification_id: int) -> None:
        response = await self.client.post(
            f"{BACKEND_URL}/api/v1/internal/notifications/{notification_id}/sent",
            headers={"X-Internal-Token": INTERNAL_API_TOKEN},
        )
        response.raise_for_status()


def build_router(bot_id: int, backend: BackendAPI, *, is_primary: bool = False) -> Router:
    router = Router()

    async def _send_plans(message: Message, *, with_miniapp_button: bool = False) -> None:
        plans = await backend.list_plans()
        text = _build_plans_message(plans)
        if with_miniapp_button:
            await message.answer(text, reply_markup=miniapp_keyboard(message.from_user.id))
            return
        await message.answer(text)

    if is_primary:
        @router.message(CommandStart())
        async def cmd_start_primary(message: Message) -> None:
            tg_user = message.from_user
            start_arg = _extract_start_arg(message.text)
            referral_code = _extract_referral_code(start_arg)
            await backend.auth_user(
                telegram_id=tg_user.id,
                username=tg_user.username,
                full_name=tg_user.full_name,
                referral_code=referral_code,
            )
            text = (
                "Уважаемые пользователи. Представленное программное обеспечение предназначено для мониторинга "
                "объявлений на платформе Авито.\n\n"
                "Целевая аудитория приложения включает:\n"
                "- Предпринимателей, занимающихся перепродажей товаров;\n"
                "- Риэлторов;\n"
                "- Пользователей, заинтересованных в поиске товаров по заданным критериям на Авито.\n\n"
                "Сферы применения: автомобили, электроника, недвижимость, запчасти, вакансии, услуги.\n\n"
                "Использование данного сервиса обеспечивает преимущество в скорости отклика и возможность "
                "приобретения товаров по наиболее выгодной цене.\n\n"
                "Программное обеспечение позволяет отслеживать новые публикации и отправлять уведомления в Telegram.\n\n"
                "Для новых пользователей предусмотрен пробный период.\n\n"
                "Желаете ли вы воспользоваться данным приложением? Для этого необходимо нажать кнопку "
                "«Открыть приложение»."
            )
            await message.answer(text, reply_markup=miniapp_keyboard(tg_user.id))

        @router.message(Command("plans"))
        async def cmd_plans_primary(message: Message) -> None:
            await _send_plans(message, with_miniapp_button=True)

        @router.message(Command("miniapp"))
        async def cmd_miniapp_primary(message: Message) -> None:
            await message.answer("Откройте miniapp", reply_markup=miniapp_keyboard(message.from_user.id))

        @router.message()
        async def any_message_primary(message: Message) -> None:
            await message.answer(
                "Этот бот предназначен для старта работы.\n"
                "Нажмите кнопку ниже, чтобы открыть MiniApp.",
                reply_markup=miniapp_keyboard(message.from_user.id),
            )

        return router

    async def _show_status(message: Message) -> None:
        status_code, payload = await backend.current_monitoring(bot_id=bot_id, telegram_id=message.from_user.id)
        if status_code == 200:
            await message.answer(
                _format_monitoring_status(payload),
                reply_markup=monitoring_actions_keyboard(message.from_user.id),
            )
            return
        await message.answer(
            f"Не удалось получить статус: {_extract_error(payload)}",
            reply_markup=monitoring_actions_keyboard(message.from_user.id),
        )

    async def _start_monitoring(message: Message) -> None:
        status_code, payload = await backend.start_monitoring(bot_id=bot_id, telegram_id=message.from_user.id)
        if status_code == 200:
            await message.answer(
                f"Мониторинг запущен.\n\n{_format_monitoring_status(payload)}",
                reply_markup=monitoring_actions_keyboard(message.from_user.id),
            )
            await _pin_monitoring_link(message.bot, chat_id=message.from_user.id, monitoring_url=payload.get("url"))
            return
        await message.answer(
            f"Не удалось запустить: {_extract_error(payload)}",
            reply_markup=monitoring_actions_keyboard(message.from_user.id),
        )

    async def _stop_monitoring(message: Message) -> None:
        status_code, payload = await backend.stop_monitoring(bot_id=bot_id, telegram_id=message.from_user.id)
        if status_code == 200:
            await message.answer(
                f"Мониторинг остановлен.\n\n{_format_monitoring_status(payload)}",
                reply_markup=monitoring_actions_keyboard(message.from_user.id),
            )
            return
        await message.answer(
            f"Не удалось остановить: {_extract_error(payload)}",
            reply_markup=monitoring_actions_keyboard(message.from_user.id),
        )

    async def _apply_change_link(message: Message, url: str) -> bool:
        status_code, payload = await backend.change_link(
            bot_id=bot_id,
            telegram_id=message.from_user.id,
            url=url,
        )
        if status_code == 200:
            await message.answer(
                "Ссылка обновлена.\n"
                f"{_format_monitoring_status(payload)}\n\n"
                "Для запуска используйте кнопку «Запустить мониторинг».",
                reply_markup=monitoring_actions_keyboard(message.from_user.id),
            )
            await _pin_monitoring_link(message.bot, chat_id=message.from_user.id, monitoring_url=payload.get("url"))
            return True
        await message.answer(
            f"Не удалось изменить ссылку: {_extract_error(payload)}",
            reply_markup=monitoring_actions_keyboard(message.from_user.id),
        )
        return False

    async def _prompt_change_link(message: Message, state: FSMContext) -> None:
        await state.set_state(LinkChangeState.waiting_url)
        await message.answer(
            "Отправьте новую ссылку на мониторинг (начинается с http:// или https://).",
            reply_markup=monitoring_actions_keyboard(message.from_user.id, include_cancel=True),
        )

    @router.message(CommandStart())
    async def cmd_start(message: Message, state: FSMContext) -> None:
        await state.clear()
        tg_user = message.from_user
        start_arg = _extract_start_arg(message.text)
        referral_code = _extract_referral_code(start_arg)
        await backend.auth_user(
            telegram_id=tg_user.id,
            username=tg_user.username,
            full_name=tg_user.full_name,
            referral_code=referral_code,
        )
        status_code, payload = await backend.current_monitoring(bot_id=bot_id, telegram_id=tg_user.id)

        if start_arg == "subscription":
            try:
                profile = await backend.get_profile(tg_user.id)
            except Exception as exc:
                logger.warning(f"Failed to load profile for subscription deep-link: {exc}")
                profile = {}

            subscription = profile.get("subscription") if isinstance(profile, dict) else None
            if subscription:
                trial_suffix = " (пробный период)" if subscription.get("is_trial") else ""
                subscription_line = (
                    f"Подписка: активна{trial_suffix}\n"
                    f"План: {subscription.get('plan_name') or '—'}\n"
                    f"До: {_format_datetime_ru(subscription.get('ends_at'))}\n"
                    f"Лимит: {subscription.get('links_limit', 0)} мониторингов"
                )
            else:
                subscription_line = "Подписка: неактивна"

            if status_code != 200:
                if status_code == 404:
                    if subscription:
                        await message.answer(
                            "Подписка активна, но этот бот не привязан к вашему мониторингу.\n"
                            "Откройте назначенного бота из раздела Подписки в miniapp.",
                            reply_markup=monitoring_actions_keyboard(tg_user.id),
                        )
                        return
                    await message.answer(
                        "Активной подписки пока нет.\n"
                        "Выберите тариф в miniapp, чтобы получить назначенного бота.",
                        reply_markup=monitoring_actions_keyboard(tg_user.id),
                    )
                    return
                await message.answer(
                    f"Не удалось получить данные подписки: {_extract_error(payload)}",
                    reply_markup=monitoring_actions_keyboard(tg_user.id),
                )
                return

            text = (
                "Данные подписки для этого бота:\n\n"
                f"{subscription_line}\n\n"
                f"{_format_monitoring_status(payload)}\n\n"
                "Управляйте мониторингом кнопками ниже."
            )
            await message.answer(text, reply_markup=monitoring_actions_keyboard(tg_user.id))
            return

        if status_code == 200:
            text = (
                "Этот бот привязан к вашему мониторингу.\n\n"
                f"{_format_monitoring_status(payload)}\n\n"
                "Управляйте мониторингом кнопками ниже."
            )
        elif status_code == 404:
            text = (
                "Этот бот пока не назначен вам.\n"
                "Купите мониторинг в miniapp и получите привязку автоматически."
            )
        else:
            text = f"Не удалось получить мониторинг: {_extract_error(payload)}"
        await message.answer(text, reply_markup=monitoring_actions_keyboard(tg_user.id))

    @router.message(Command("plans"))
    async def cmd_plans(message: Message) -> None:
        await _send_plans(message)

    @router.message(Command("status"))
    async def cmd_status(message: Message) -> None:
        await _show_status(message)

    @router.message(Command("start_monitoring"))
    async def cmd_start_monitoring(message: Message) -> None:
        await _start_monitoring(message)

    @router.message(Command("stop_monitoring"))
    async def cmd_stop_monitoring(message: Message) -> None:
        await _stop_monitoring(message)

    @router.message(Command("change_link"))
    async def cmd_change_link(message: Message, state: FSMContext) -> None:
        parts = (message.text or "").split(maxsplit=1)
        if len(parts) < 2:
            await _prompt_change_link(message, state)
            return
        url = parts[1].strip()
        if not _looks_like_url(url):
            await message.answer(
                "Ссылка должна начинаться с http:// или https://",
                reply_markup=monitoring_actions_keyboard(message.from_user.id),
            )
            return
        await state.clear()
        await _apply_change_link(message, url)

    @router.message(LinkChangeState.waiting_url)
    async def on_change_link_input(message: Message, state: FSMContext) -> None:
        value = (message.text or "").strip()
        if value == BTN_CANCEL_CHANGE:
            await state.clear()
            await message.answer(
                "Изменение ссылки отменено.",
                reply_markup=monitoring_actions_keyboard(message.from_user.id),
            )
            return
        if not _looks_like_url(value):
            await message.answer(
                "Нужна ссылка формата https://... Повторите ввод или нажмите «Отмена изменения».",
                reply_markup=monitoring_actions_keyboard(message.from_user.id, include_cancel=True),
            )
            return

        await state.clear()
        await _apply_change_link(message, value)

    @router.message(F.text == BTN_STATUS)
    async def btn_status(message: Message) -> None:
        await _show_status(message)

    @router.message(F.text == BTN_START_MONITORING)
    async def btn_start(message: Message) -> None:
        await _start_monitoring(message)

    @router.message(F.text == BTN_STOP_MONITORING)
    async def btn_stop(message: Message) -> None:
        await _stop_monitoring(message)

    @router.message(F.text == BTN_CHANGE_LINK)
    async def btn_change_link(message: Message, state: FSMContext) -> None:
        await _prompt_change_link(message, state)

    @router.message(Command("miniapp"))
    async def cmd_miniapp(message: Message) -> None:
        await message.answer("Откройте miniapp", reply_markup=miniapp_keyboard(message.from_user.id))

    @router.message(F.text == BTN_OPEN_MINIAPP)
    async def btn_miniapp(message: Message) -> None:
        await cmd_miniapp(message)

    return router


@dataclass
class BotRuntime:
    bot_id: int
    token: str
    is_primary: bool
    bot: Bot
    dispatcher: Dispatcher
    task: asyncio.Task[None]


class MultiBotManager:
    def __init__(self, backend: BackendAPI) -> None:
        self.backend = backend
        self.runtimes: dict[int, BotRuntime] = {}

    async def start_bot(self, config: dict[str, Any]) -> None:
        bot_id = int(config["id"])
        token = str(config.get("bot_token", "")).strip()
        is_primary = bool(config.get("is_primary", False))
        if not has_valid_bot_token(token):
            logger.error(f"Bot #{bot_id} has invalid token, skipping")
            return

        bot = Bot(token=token)
        try:
            me = await bot.get_me()
            await self.backend.sync_bot_metadata(bot_id=bot_id, telegram_bot_id=me.id, bot_username=me.username)
            if is_primary:
                await bot.set_my_commands(
                    [
                        BotCommand(command="miniapp", description="Открыть miniapp"),
                    ]
                )
            else:
                await bot.set_my_commands(
                    [
                        BotCommand(command="start_monitoring", description="Запустить мониторинг"),
                        BotCommand(command="stop_monitoring", description="Остановить мониторинг"),
                        BotCommand(command="change_link", description="Поменять ссылку"),
                        BotCommand(command="status", description="Статус мониторинга"),
                        BotCommand(command="miniapp", description="Открыть miniapp"),
                    ]
                )
        except Exception as exc:
            logger.error(f"Failed to initialize bot #{bot_id}: {exc}")
            await bot.session.close()
            return

        dispatcher = Dispatcher()
        dispatcher.include_router(build_router(bot_id=bot_id, backend=self.backend, is_primary=is_primary))
        task = asyncio.create_task(dispatcher.start_polling(bot))
        self.runtimes[bot_id] = BotRuntime(
            bot_id=bot_id,
            token=token,
            is_primary=is_primary,
            bot=bot,
            dispatcher=dispatcher,
            task=task,
        )
        logger.info(f"Started polling for bot #{bot_id} (@{me.username or 'unknown'})")

    async def stop_bot(self, bot_id: int) -> None:
        runtime = self.runtimes.pop(bot_id, None)
        if not runtime:
            return
        with suppress(Exception):
            await runtime.dispatcher.stop_polling()
        runtime.task.cancel()
        with suppress(asyncio.CancelledError):
            await runtime.task
        await runtime.bot.session.close()
        logger.info(f"Stopped bot #{bot_id}")

    async def sync_bots(self) -> None:
        try:
            active_configs = await self.backend.active_bots()
        except Exception as exc:
            logger.error(f"Failed to fetch active bots: {exc}")
            return

        incoming: dict[int, dict[str, Any]] = {}
        for cfg in active_configs:
            try:
                incoming[int(cfg["id"])] = cfg
            except Exception:
                continue

        for bot_id in list(self.runtimes.keys()):
            runtime = self.runtimes.get(bot_id)
            if not runtime:
                continue
            if bot_id not in incoming:
                await self.stop_bot(bot_id)
                continue

            new_token = str(incoming[bot_id].get("bot_token", "")).strip()
            new_is_primary = bool(incoming[bot_id].get("is_primary", False))
            if runtime.task.done() or runtime.token != new_token or runtime.is_primary != new_is_primary:
                await self.stop_bot(bot_id)

        for bot_id, cfg in incoming.items():
            if bot_id not in self.runtimes:
                await self.start_bot(cfg)

    async def close(self) -> None:
        for bot_id in list(self.runtimes.keys()):
            await self.stop_bot(bot_id)


async def bots_sync_loop(manager: MultiBotManager, stop_event: asyncio.Event) -> None:
    while not stop_event.is_set():
        await manager.sync_bots()
        await asyncio.sleep(BOTS_REFRESH_SEC)


async def notifications_loop(manager: MultiBotManager, backend: BackendAPI, stop_event: asyncio.Event) -> None:
    rate_limit_cooldowns: dict[tuple[int, int, int], datetime] = {}
    burst_warning_cooldowns: dict[tuple[int, int, int], datetime] = {}
    monitoring_recent_sent: dict[int, deque[datetime]] = {}
    send_semaphore = asyncio.Semaphore(max(1, NOTIFY_SEND_CONCURRENCY))

    async def deliver_notification(notification: dict[str, Any]) -> None:
        bot_id = int(notification.get("bot_id") or 0)
        runtime = manager.runtimes.get(bot_id)
        if not runtime:
            return

        async with send_semaphore:
            try:
                text = str(notification.get("message") or "").strip()
                photo_url = str(notification.get("photo_url") or "").strip()
                if photo_url:
                    try:
                        if len(text) > 1000:
                            await _send_photo_with_retry(
                                bot=runtime.bot,
                                chat_id=notification["telegram_id"],
                                photo_url=photo_url,
                            )
                            await runtime.bot.send_message(
                                chat_id=notification["telegram_id"],
                                text=text,
                                parse_mode="HTML",
                                disable_web_page_preview=True,
                            )
                        else:
                            await _send_photo_with_retry(
                                bot=runtime.bot,
                                chat_id=notification["telegram_id"],
                                photo_url=photo_url,
                                caption=_fit_photo_caption(text),
                                parse_mode="HTML",
                            )
                    except Exception as exc:
                        logger.warning(
                            "send_photo failed for notification id={} photo_url={}: {}",
                            notification.get("id"),
                            photo_url,
                            exc,
                        )
                        await _maybe_send_rate_limit_warning(runtime, notification, exc, rate_limit_cooldowns)
                        sent_with_download = False
                        downloaded = await _download_photo_bytes(photo_url)
                        if downloaded:
                            photo_data, filename = downloaded
                            try:
                                if len(text) > 1000:
                                    await _send_downloaded_photo_with_retry(
                                        bot=runtime.bot,
                                        chat_id=notification["telegram_id"],
                                        photo_data=photo_data,
                                        filename=filename,
                                    )
                                    await runtime.bot.send_message(
                                        chat_id=notification["telegram_id"],
                                        text=text,
                                        parse_mode="HTML",
                                        disable_web_page_preview=True,
                                    )
                                else:
                                    await _send_downloaded_photo_with_retry(
                                        bot=runtime.bot,
                                        chat_id=notification["telegram_id"],
                                        photo_data=photo_data,
                                        filename=filename,
                                        caption=_fit_photo_caption(text),
                                        parse_mode="HTML",
                                    )
                                sent_with_download = True
                            except Exception as download_exc:
                                logger.warning(
                                    "send_photo(downloaded) failed for notification id={} photo_url={}: {}",
                                    notification.get("id"),
                                    photo_url,
                                    download_exc,
                                )

                        if not sent_with_download:
                            await runtime.bot.send_message(
                                chat_id=notification["telegram_id"],
                                text=text,
                                parse_mode="HTML",
                                disable_web_page_preview=False,
                            )
                else:
                    await runtime.bot.send_message(
                        chat_id=notification["telegram_id"],
                        text=text,
                        parse_mode="HTML",
                        disable_web_page_preview=False,
                    )
                await backend.mark_notification_sent(notification["id"])
            except Exception as exc:
                await _maybe_send_rate_limit_warning(runtime, notification, exc, rate_limit_cooldowns)
                logger.warning(f"Failed to deliver notification id={notification.get('id')}: {exc}")

    while not stop_event.is_set():
        had_notifications = False
        now = datetime.now(timezone.utc)
        stale_keys = [key for key, expires_at in rate_limit_cooldowns.items() if expires_at <= now]
        for key in stale_keys:
            rate_limit_cooldowns.pop(key, None)
        stale_burst_keys = [key for key, expires_at in burst_warning_cooldowns.items() if expires_at <= now]
        for key in stale_burst_keys:
            burst_warning_cooldowns.pop(key, None)

        window_cutoff = now - timedelta(seconds=max(1.0, MONITORING_BURST_WINDOW_SEC))
        for monitoring_id in list(monitoring_recent_sent.keys()):
            bucket = monitoring_recent_sent.get(monitoring_id)
            if not bucket:
                monitoring_recent_sent.pop(monitoring_id, None)
                continue
            while bucket and bucket[0] <= window_cutoff:
                bucket.popleft()
            if not bucket:
                monitoring_recent_sent.pop(monitoring_id, None)

        try:
            notifications = await backend.pending_notifications(limit=max(1, min(NOTIFY_FETCH_LIMIT, 500)))
            had_notifications = bool(notifications)
            if notifications:
                allowed_notifications: list[dict[str, Any]] = []
                dropped_notifications = 0

                for notification in notifications:
                    bot_id = int(notification.get("bot_id") or 0)
                    runtime = manager.runtimes.get(bot_id)
                    if not runtime:
                        allowed_notifications.append(notification)
                        continue

                    monitoring_id = int(notification.get("monitoring_id") or 0)
                    if (
                        monitoring_id <= 0
                        or MONITORING_BURST_MAX_MESSAGES <= 0
                        or MONITORING_BURST_WINDOW_SEC <= 0
                    ):
                        allowed_notifications.append(notification)
                        continue

                    bucket = monitoring_recent_sent.setdefault(monitoring_id, deque())
                    cutoff = datetime.now(timezone.utc) - timedelta(seconds=max(1.0, MONITORING_BURST_WINDOW_SEC))
                    while bucket and bucket[0] <= cutoff:
                        bucket.popleft()

                    if len(bucket) >= MONITORING_BURST_MAX_MESSAGES:
                        dropped_notifications += 1
                        try:
                            await backend.mark_notification_sent(notification["id"])
                        except Exception as mark_exc:
                            logger.warning(
                                "Failed to drop notification id={} for monitoring={} by burst limiter: {}",
                                notification.get("id"),
                                monitoring_id,
                                mark_exc,
                            )
                            continue
                        await _maybe_send_monitoring_burst_warning(runtime, notification, burst_warning_cooldowns)
                        continue

                    bucket.append(datetime.now(timezone.utc))
                    allowed_notifications.append(notification)

                if dropped_notifications:
                    logger.warning(
                        "Burst limiter dropped {} notifications in this cycle (window={}s max={})",
                        dropped_notifications,
                        MONITORING_BURST_WINDOW_SEC,
                        MONITORING_BURST_MAX_MESSAGES,
                    )

                if allowed_notifications:
                    await asyncio.gather(*(deliver_notification(notification) for notification in allowed_notifications))
        except Exception as exc:
            logger.error(f"Notifications loop failed: {exc}")

        sleep_for = NOTIFY_BACKLOG_POLL_SEC if had_notifications else NOTIFY_POLL_SEC
        await asyncio.sleep(max(0.05, sleep_for))


async def main() -> None:
    backend = BackendAPI()
    manager = MultiBotManager(backend=backend)
    stop_event = asyncio.Event()

    sync_task = asyncio.create_task(bots_sync_loop(manager=manager, stop_event=stop_event))
    notify_task = asyncio.create_task(notifications_loop(manager=manager, backend=backend, stop_event=stop_event))

    try:
        await asyncio.gather(sync_task, notify_task)
    finally:
        stop_event.set()
        sync_task.cancel()
        notify_task.cancel()
        with suppress(asyncio.CancelledError):
            await sync_task
        with suppress(asyncio.CancelledError):
            await notify_task
        await manager.close()
        await backend.close()


if __name__ == "__main__":
    asyncio.run(main())
