# AvitoBot Platform (Bot + MiniApp + Admin + Parser)

Единая платформа вокруг основной бизнес-цели: **монетизация парсинга Avito**.

## Контейнеры (7)
1. `bot` — Telegram bot (`aiogram3`)
2. `miniapp-frontend` — Telegram MiniApp frontend (`React + Vite`)
3. `miniapp-backend` — API и бизнес-логика (`FastAPI`)
4. `admin-panel` — админ-панель (на основе TeleAdminPanel, `Express + EJS`)
5. `db` — PostgreSQL
6. `nginx` — роутинг `/`, `/api`, `/admin`
7. `avito-parser` — отдельный воркер парсинга Avito

## Что уже реализовано
- Полный docker-контур на 7 сервисов.
- FastAPI backend с БД-моделями:
  - пользователи
  - тарифные планы
  - подписки
  - мониторинги ссылок
  - найденные объявления
  - прокси
  - платежи
  - уведомления
- Seed стартовых тарифов:
  - 1 ссылка / 7 дней / 100 ₽
  - 1 ссылка / 30 дней / 500 ₽
  - 3 ссылки / 7 дней / 250 ₽
- Отдельный parser-worker:
  - берёт активные мониторинги
  - парсит Avito
  - сохраняет новые объявления через internal API
  - создаёт уведомления для бота
- Telegram bot на `aiogram3`:
  - мультибот-режим (боты берутся из БД, можно добавлять/выключать в админке)
  - команды внутри назначенного бота:
    - `/start_monitoring`
    - `/stop_monitoring`
    - `/change_link <url>`
    - `/status`
  - фоновая доставка новых объявлений строго через назначенного бота мониторинга
- React miniapp:
  - темная тема и нижняя навигация из 3 разделов:
    - Информация (поддержка/FAQ/новости/документы)
    - Подписки (активные боты, тарифы, покупка подписки, покупка мониторинга)
    - Профиль (реферальная ссылка, реф. баланс, Telegram ID)
  - автоаутентификация через Telegram WebApp
- Админ-панель:
  - dashboard/статистика
  - управление пулом Telegram-ботов
  - управление тарифами (изменение стоимости + добавление своих)
  - управление прокси
  - просмотр пользователей/мониторингов
  - просмотр и ручное добавление платежей
  - активация подписки пользователю

## Важная интеграция с `parser_avito`
Логика парсинга встроена в сервис `avito-parser` через модуль:
- `avito-parser-service/app/avito_adapter.py`

Используются компоненты из репозитория `parser_avito`:
- `models.py` (`ItemsResponse`, `Item`)
- `dto.py` (`AvitoConfig`)
- `filters/ads_filter.py` (`AdsFilter`)
- `common_data.py` (`HEADERS`)

## Запуск
1. Создать `.env` на базе `.env.example`:
```bash
cp .env.example .env
```
2. Заполнить `BOT_TOKEN` и токены `INTERNAL_API_TOKEN`/`ADMIN_API_TOKEN`.
3. Запуск:
```bash
docker compose up --build
```
4. Точки входа:
- MiniApp: `http://localhost/`
- API: `http://localhost/api/...`
- Admin: `http://localhost/admin/`

## Phase checklist
- [x] Этап 1: инфраструктура Docker + nginx + БД
- [x] Этап 2: backend API + модели + тарифы
- [x] Этап 3: parser-worker + интеграция логики parser_avito
- [x] Этап 4: Telegram bot aiogram3
- [x] Этап 5: MiniApp React
- [x] Этап 6: Admin panel (TeleAdminPanel template -> рабочая панель)
- [ ] Этап 7: прод-усиление (реальные платежные провайдеры, полноценная auth-валидация Telegram initData, очередь задач, ретраи/метрики, e2e тесты)

## Примечание
Текущая версия — полноценный MVP для продажи услуги мониторинга Avito.
Для production рекомендуется отдельно добавить:
- устойчивый антиблок (без прокси Avito часто отвечает `429 Too Many Requests`)
- проверку подписи `initData` Telegram MiniApp
- интеграцию платёжного шлюза (YooKassa/CloudPayments и т.п.)
- очередь задач (Redis + Celery/RQ) для высоких нагрузок
- централизованные логи и алерты
