from __future__ import annotations

import asyncio
from datetime import datetime
import hashlib
import hmac
import os
from contextlib import suppress
from dataclasses import dataclass
from typing import Any
from urllib.parse import parse_qsl, urlencode, urlsplit, urlunsplit

import httpx
from aiogram import Bot, Dispatcher, Router
from aiogram.client.default import DefaultBotProperties
from aiogram.enums import ParseMode
from aiogram.filters import Command, CommandStart
from aiogram.types import BotCommand, InlineKeyboardButton, InlineKeyboardMarkup, Message, WebAppInfo
from aiogram.utils.token import TokenValidationError, validate_token
from loguru import logger


BACKEND_URL = os.getenv("BACKEND_URL", "http://miniapp-backend:8000").rstrip("/")
INTERNAL_API_TOKEN = os.getenv("INTERNAL_API_TOKEN", "change_me_internal_token")
MINIAPP_PUBLIC_URL = os.getenv("MINIAPP_PUBLIC_URL", "http://localhost")
MINIAPP_AUTH_SECRET = os.getenv("MINIAPP_AUTH_SECRET", "change_me_miniapp_auth_secret")
BOTS_REFRESH_SEC = int(os.getenv("BOTS_REFRESH_SEC", "15"))
NOTIFY_POLL_SEC = int(os.getenv("NOTIFY_POLL_SEC", "4"))


def has_valid_bot_token(token: str) -> bool:
    if not token:
        return False
    try:
        validate_token(token)
    except TokenValidationError:
        return False
    return True


def build_miniapp_auth_token(telegram_id: int) -> str:
    telegram_raw = str(telegram_id)
    signature = hmac.new(
        MINIAPP_AUTH_SECRET.encode("utf-8"),
        telegram_raw.encode("utf-8"),
        hashlib.sha256,
    ).hexdigest()[:24]
    return f"{telegram_raw}.{signature}"


def build_miniapp_url(telegram_id: int) -> str:
    parsed = urlsplit(MINIAPP_PUBLIC_URL)
    query = dict(parse_qsl(parsed.query, keep_blank_values=True))
    query["auth"] = build_miniapp_auth_token(telegram_id)
    return urlunsplit((parsed.scheme, parsed.netloc, parsed.path, urlencode(query), parsed.fragment))


def miniapp_keyboard(telegram_id: int) -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [InlineKeyboardButton(text="Открыть MiniApp", web_app=WebAppInfo(url=build_miniapp_url(telegram_id)))],
        ]
    )


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


class BackendAPI:
    def __init__(self) -> None:
        self.client = httpx.AsyncClient(timeout=30)

    async def close(self) -> None:
        await self.client.aclose()

    async def auth_user(self, telegram_id: int, username: str | None, full_name: str | None) -> dict[str, Any]:
        payload = {
            "telegram_id": telegram_id,
            "username": username,
            "full_name": full_name,
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


def build_router(bot_id: int, backend: BackendAPI) -> Router:
    router = Router()

    @router.message(CommandStart())
    async def cmd_start(message: Message) -> None:
        tg_user = message.from_user
        await backend.auth_user(
            telegram_id=tg_user.id,
            username=tg_user.username,
            full_name=tg_user.full_name,
        )
        start_arg = _extract_start_arg(message.text)
        status_code, payload = await backend.current_monitoring(bot_id=bot_id, telegram_id=tg_user.id)

        if start_arg == "subscription":
            if status_code != 200:
                if status_code == 404:
                    await message.answer(
                        "Подписка для этого бота пока не назначена.\n"
                        "Купите мониторинг в miniapp, чтобы активировать этот бот."
                    )
                    return
                await message.answer(f"Не удалось получить данные подписки: {_extract_error(payload)}")
                return

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

            text = (
                "Данные подписки для этого бота:\n\n"
                f"{subscription_line}\n\n"
                f"{_format_monitoring_status(payload)}\n\n"
                "Команды:\n"
                "/start_monitoring - запустить мониторинг\n"
                "/stop_monitoring - остановить мониторинг\n"
                "/change_link <url> - поменять ссылку"
            )
            await message.answer(text, reply_markup=miniapp_keyboard(tg_user.id))
            return

        if status_code == 200:
            text = (
                "Этот бот привязан к вашему мониторингу.\n\n"
                f"{_format_monitoring_status(payload)}\n\n"
                "Команды:\n"
                "/start_monitoring - запустить мониторинг\n"
                "/stop_monitoring - остановить мониторинг\n"
                "/change_link <url> - поменять ссылку\n"
                "/status - текущий статус\n"
                "/miniapp - открыть miniapp"
            )
        elif status_code == 404:
            text = (
                "Этот бот пока не назначен вам.\n"
                "Купите мониторинг в miniapp и получите привязку автоматически."
            )
        else:
            text = f"Не удалось получить мониторинг: {_extract_error(payload)}"
        await message.answer(text, reply_markup=miniapp_keyboard(tg_user.id))

    @router.message(Command("plans"))
    async def cmd_plans(message: Message) -> None:
        plans = await backend.list_plans()
        if not plans:
            await message.answer("Тарифы пока не настроены в админ-панели.")
            return
        lines = ["Доступные тарифы:"]
        for plan in plans:
            lines.append(
                f"• {plan['name']}: {plan['price_rub']}₽ | {plan['links_limit']} мониторингов | {plan['duration_days']} дней"
            )
        await message.answer("\n".join(lines))

    @router.message(Command("status"))
    async def cmd_status(message: Message) -> None:
        status_code, payload = await backend.current_monitoring(bot_id=bot_id, telegram_id=message.from_user.id)
        if status_code == 200:
            await message.answer(_format_monitoring_status(payload))
            return
        await message.answer(f"Не удалось получить статус: {_extract_error(payload)}")

    @router.message(Command("start_monitoring"))
    async def cmd_start_monitoring(message: Message) -> None:
        status_code, payload = await backend.start_monitoring(bot_id=bot_id, telegram_id=message.from_user.id)
        if status_code == 200:
            await message.answer(f"Мониторинг запущен.\n\n{_format_monitoring_status(payload)}")
            return
        await message.answer(f"Не удалось запустить: {_extract_error(payload)}")

    @router.message(Command("stop_monitoring"))
    async def cmd_stop_monitoring(message: Message) -> None:
        status_code, payload = await backend.stop_monitoring(bot_id=bot_id, telegram_id=message.from_user.id)
        if status_code == 200:
            await message.answer(f"Мониторинг остановлен.\n\n{_format_monitoring_status(payload)}")
            return
        await message.answer(f"Не удалось остановить: {_extract_error(payload)}")

    @router.message(Command("change_link"))
    async def cmd_change_link(message: Message) -> None:
        parts = (message.text or "").split(maxsplit=1)
        if len(parts) < 2:
            await message.answer("Использование: /change_link https://www.avito.ru/...")
            return
        url = parts[1].strip()
        status_code, payload = await backend.change_link(
            bot_id=bot_id,
            telegram_id=message.from_user.id,
            url=url,
        )
        if status_code == 200:
            await message.answer(
                "Ссылка обновлена.\n"
                f"{_format_monitoring_status(payload)}\n\n"
                "Для запуска используйте /start_monitoring"
            )
            return
        await message.answer(f"Не удалось изменить ссылку: {_extract_error(payload)}")

    @router.message(Command("miniapp"))
    async def cmd_miniapp(message: Message) -> None:
        await message.answer("Откройте miniapp", reply_markup=miniapp_keyboard(message.from_user.id))

    return router


@dataclass
class BotRuntime:
    bot_id: int
    token: str
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
        if not has_valid_bot_token(token):
            logger.error(f"Bot #{bot_id} has invalid token, skipping")
            return

        bot = Bot(token=token, default=DefaultBotProperties(parse_mode=ParseMode.HTML))
        try:
            me = await bot.get_me()
            await self.backend.sync_bot_metadata(bot_id=bot_id, telegram_bot_id=me.id, bot_username=me.username)
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
        dispatcher.include_router(build_router(bot_id=bot_id, backend=self.backend))
        task = asyncio.create_task(dispatcher.start_polling(bot))
        self.runtimes[bot_id] = BotRuntime(
            bot_id=bot_id,
            token=token,
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
            if runtime.task.done() or runtime.token != new_token:
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
    while not stop_event.is_set():
        try:
            notifications = await backend.pending_notifications(limit=100)
            for notification in notifications:
                bot_id = int(notification.get("bot_id") or 0)
                runtime = manager.runtimes.get(bot_id)
                if not runtime:
                    continue
                try:
                    await runtime.bot.send_message(
                        chat_id=notification["telegram_id"],
                        text=notification["message"],
                        disable_web_page_preview=True,
                    )
                    await backend.mark_notification_sent(notification["id"])
                except Exception as exc:
                    logger.warning(f"Failed to deliver notification id={notification.get('id')}: {exc}")
        except Exception as exc:
            logger.error(f"Notifications loop failed: {exc}")

        await asyncio.sleep(NOTIFY_POLL_SEC)


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
