import logging
from threading import Event, Thread

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app.config import settings
from app.database import SessionLocal
from app.routers.admin import router as admin_router
from app.routers.internal import router as internal_router
from app.routers.public import router as public_router, webhook_router
from app.services.bootstrap import init_db, seed_default_plans
from app.services.helpers import notify_expiring_proxies


app = FastAPI(title=settings.app_name)
logger = logging.getLogger(__name__)
_proxy_notifier_stop_event: Event | None = None
_proxy_notifier_thread: Thread | None = None
_PROXY_NOTIFIER_INTERVAL_SECONDS = 3600

origins = [x.strip() for x in settings.cors_origins.split(",") if x.strip()]
app.add_middleware(
    CORSMiddleware,
    allow_origins=origins if origins else ["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


@app.on_event("startup")
def startup_event() -> None:
    global _proxy_notifier_stop_event, _proxy_notifier_thread
    init_db()
    db = SessionLocal()
    try:
        seed_default_plans(db)
        notify_expiring_proxies(db)
    finally:
        db.close()

    if _proxy_notifier_thread and _proxy_notifier_thread.is_alive():
        return

    _proxy_notifier_stop_event = Event()
    _proxy_notifier_thread = Thread(
        target=_run_proxy_expiry_notifier,
        args=(_proxy_notifier_stop_event,),
        daemon=True,
        name="proxy-expiry-notifier",
    )
    _proxy_notifier_thread.start()


@app.on_event("shutdown")
def shutdown_event() -> None:
    global _proxy_notifier_stop_event, _proxy_notifier_thread
    if _proxy_notifier_stop_event:
        _proxy_notifier_stop_event.set()
    if _proxy_notifier_thread and _proxy_notifier_thread.is_alive():
        _proxy_notifier_thread.join(timeout=2)
    _proxy_notifier_stop_event = None
    _proxy_notifier_thread = None


def _run_proxy_expiry_notifier(stop_event: Event) -> None:
    while not stop_event.is_set():
        db = SessionLocal()
        try:
            notify_expiring_proxies(db)
        except Exception:
            logger.exception("Proxy expiry notifier failed")
        finally:
            db.close()
        stop_event.wait(_PROXY_NOTIFIER_INTERVAL_SECONDS)


@app.get("/health")
def health() -> dict:
    return {"status": "ok"}


api_prefix = "/api/v1"
app.include_router(webhook_router)
app.include_router(public_router, prefix=api_prefix)
app.include_router(admin_router, prefix=api_prefix)
app.include_router(internal_router, prefix=api_prefix)
