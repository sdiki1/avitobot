from __future__ import annotations

import asyncio
import os
from typing import Any

from aiogram import Bot, Dispatcher, Router
from aiogram.enums import ParseMode
from aiogram.filters import Command, CommandStart
from aiogram.types import InlineKeyboardButton, InlineKeyboardMarkup, Message, WebAppInfo
from aiogram.client.default import DefaultBotProperties
from aiogram.utils.token import TokenValidationError, validate_token
import httpx
from loguru import logger


BOT_TOKEN = os.getenv("BOT_TOKEN", "")
BACKEND_URL = os.getenv("BACKEND_URL", "http://miniapp-backend:8000").rstrip("/")
INTERNAL_API_TOKEN = os.getenv("INTERNAL_API_TOKEN", "change_me_internal_token")
MINIAPP_PUBLIC_URL = os.getenv("MINIAPP_PUBLIC_URL", "http://localhost")

def has_valid_bot_token(token: str) -> bool:
    if not token:
        return False
    try:
        validate_token(token)
    except TokenValidationError:
        return False
    return True


router = Router()


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
        return response.json()

    async def list_monitorings(self, telegram_id: int) -> list[dict[str, Any]]:
        response = await self.client.get(
            f"{BACKEND_URL}/api/v1/public/monitorings",
            params={"telegram_id": telegram_id},
        )
        response.raise_for_status()
        return response.json()

    async def add_monitoring(self, telegram_id: int, url: str) -> tuple[int, dict[str, Any]]:
        payload = {
            "telegram_id": telegram_id,
            "url": url,
            "title": None,
            "keywords_white": [],
            "keywords_black": [],
            "min_price": None,
            "max_price": None,
            "geo": None,
        }
        response = await self.client.post(f"{BACKEND_URL}/api/v1/public/monitorings", json=payload)
        return response.status_code, response.json()

    async def pending_notifications(self, limit: int = 100) -> list[dict[str, Any]]:
        response = await self.client.get(
            f"{BACKEND_URL}/api/v1/internal/notifications/pending",
            params={"limit": limit},
            headers={"X-Internal-Token": INTERNAL_API_TOKEN},
        )
        response.raise_for_status()
        return response.json()

    async def mark_notification_sent(self, notification_id: int) -> None:
        response = await self.client.post(
            f"{BACKEND_URL}/api/v1/internal/notifications/{notification_id}/sent",
            headers={"X-Internal-Token": INTERNAL_API_TOKEN},
        )
        response.raise_for_status()


backend = BackendAPI()


def miniapp_keyboard(telegram_id: int) -> InlineKeyboardMarkup:
    url = f"{MINIAPP_PUBLIC_URL}?tg_id={telegram_id}"
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [InlineKeyboardButton(text="Открыть MiniApp", web_app=WebAppInfo(url=url))],
        ]
    )


@router.message(CommandStart())
async def cmd_start(message: Message) -> None:
    tg_user = message.from_user
    await backend.auth_user(
        telegram_id=tg_user.id,
        username=tg_user.username,
        full_name=tg_user.full_name,
    )

    text = (
        "Avito мониторинг запущен.\n"
        "Основной продукт: поиск новых объявлений на Avito по вашим ссылкам.\n\n"
        "Команды:\n"
        "/plans - тарифы\n"
        "/my_links - мои ссылки\n"
        "/add_link <url> - добавить ссылку\n"
        "/miniapp - открыть miniapp"
    )
    await message.answer(text, reply_markup=miniapp_keyboard(tg_user.id))


@router.message(Command("plans"))
async def cmd_plans(message: Message) -> None:
    plans = await backend.list_plans()
    if not plans:
        await message.answer("Тарифы пока не настроены в админ-панели")
        return

    lines = ["Доступные тарифы:"]
    for p in plans:
        lines.append(
            f"• {p['name']}: {p['price_rub']}₽ | {p['links_limit']} ссылок | {p['duration_days']} дней"
        )
    await message.answer("\n".join(lines))


@router.message(Command("my_links"))
async def cmd_my_links(message: Message) -> None:
    tg_id = message.from_user.id
    monitorings = await backend.list_monitorings(tg_id)
    if not monitorings:
        await message.answer("У вас пока нет активных ссылок. Добавьте через /add_link или miniapp.")
        return

    lines = ["Ваши ссылки мониторинга:"]
    for m in monitorings:
        lines.append(f"• #{m['id']} {m.get('title') or '-'}\n{m['url']}")
    await message.answer("\n\n".join(lines))


@router.message(Command("add_link"))
async def cmd_add_link(message: Message) -> None:
    parts = (message.text or "").split(maxsplit=1)
    if len(parts) < 2:
        await message.answer("Использование: /add_link https://www.avito.ru/...")
        return

    url = parts[1].strip()
    status_code, payload = await backend.add_monitoring(message.from_user.id, url)
    if status_code == 200:
        await message.answer(f"Ссылка добавлена в мониторинг: #{payload['id']}")
        return

    error_message = payload.get("detail") if isinstance(payload, dict) else str(payload)
    await message.answer(f"Не удалось добавить ссылку: {error_message}")


@router.message(Command("miniapp"))
async def cmd_miniapp(message: Message) -> None:
    await message.answer("Откройте miniapp", reply_markup=miniapp_keyboard(message.from_user.id))


async def notifications_loop(bot: Bot, stop_event: asyncio.Event) -> None:
    while not stop_event.is_set():
        try:
            notifications = await backend.pending_notifications(limit=100)
            for n in notifications:
                try:
                    await bot.send_message(
                        chat_id=n["telegram_id"],
                        text=n["message"],
                        disable_web_page_preview=True,
                    )
                    await backend.mark_notification_sent(n["id"])
                except Exception as exc:
                    logger.warning(f"Failed to deliver notification id={n.get('id')}: {exc}")
        except Exception as exc:
            logger.error(f"notifications loop failed: {exc}")

        await asyncio.sleep(4)


async def main() -> None:
    if not has_valid_bot_token(BOT_TOKEN):
        logger.error("BOT_TOKEN is invalid or empty. Set real token in .env, then restart bot container.")
        while True:
            await asyncio.sleep(3600)

    bot = Bot(token=BOT_TOKEN, default=DefaultBotProperties(parse_mode=ParseMode.HTML))
    dp = Dispatcher()
    dp.include_router(router)

    stop_event = asyncio.Event()
    notify_task = asyncio.create_task(notifications_loop(bot, stop_event))

    try:
        await dp.start_polling(bot)
    finally:
        stop_event.set()
        notify_task.cancel()
        await backend.close()
        await bot.session.close()


if __name__ == "__main__":
    asyncio.run(main())
