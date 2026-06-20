import logging
from threading import Event, Thread
from urllib.parse import parse_qsl, urlencode

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from starlette.types import Message

from app.config import settings
from app.database import SessionLocal
from app.routers.admin import router as admin_router
from app.routers.internal import router as internal_router
from app.routers.public import router as public_router, webhook_router
from app.services.bootstrap import init_db, seed_default_plans
from app.services.helpers import maintain_proxy_pool


app = FastAPI(title=settings.app_name)
logger = logging.getLogger(__name__)
_proxy_maintenance_stop_event: Event | None = None
_proxy_maintenance_thread: Thread | None = None
_PROXY_MAINTENANCE_INTERVAL_SECONDS = 3600

origins = [x.strip() for x in settings.cors_origins.split(",") if x.strip()]
app.add_middleware(
    CORSMiddleware,
    allow_origins=origins if origins else ["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


@app.middleware("http")
async def restore_get_body_from_query(request, call_next):
    if request.method == "GET" and "__body" in request.query_params:
        pairs = parse_qsl(request.scope.get("query_string", b"").decode("utf-8"), keep_blank_values=True)
        body_values = [value for key, value in pairs if key == "__body"]
        filtered_query = urlencode([(key, value) for key, value in pairs if key != "__body"], doseq=True)
        request.scope["query_string"] = filtered_query.encode("utf-8")

        body = (body_values[-1] if body_values else "").encode("utf-8")
        request.scope["headers"] = [
            (key, value)
            for key, value in request.scope.get("headers", [])
            if key.lower() not in {b"content-type", b"content-length"}
        ]
        request.scope["headers"].append((b"content-type", b"application/json"))
        request.scope["headers"].append((b"content-length", str(len(body)).encode("ascii")))

        async def receive() -> Message:
            return {"type": "http.request", "body": body, "more_body": False}

        request._receive = receive

    return await call_next(request)


@app.on_event("startup")
def startup_event() -> None:
    global _proxy_maintenance_stop_event, _proxy_maintenance_thread
    init_db()
    db = SessionLocal()
    try:
        seed_default_plans(db)
        maintain_proxy_pool(db)
    finally:
        db.close()

    if _proxy_maintenance_thread and _proxy_maintenance_thread.is_alive():
        return

    _proxy_maintenance_stop_event = Event()
    _proxy_maintenance_thread = Thread(
        target=_run_proxy_maintenance,
        args=(_proxy_maintenance_stop_event,),
        daemon=True,
        name="proxy-maintenance",
    )
    _proxy_maintenance_thread.start()


@app.on_event("shutdown")
def shutdown_event() -> None:
    global _proxy_maintenance_stop_event, _proxy_maintenance_thread
    if _proxy_maintenance_stop_event:
        _proxy_maintenance_stop_event.set()
    if _proxy_maintenance_thread and _proxy_maintenance_thread.is_alive():
        _proxy_maintenance_thread.join(timeout=2)
    _proxy_maintenance_stop_event = None
    _proxy_maintenance_thread = None


def _run_proxy_maintenance(stop_event: Event) -> None:
    while not stop_event.is_set():
        db = SessionLocal()
        try:
            maintain_proxy_pool(db)
        except Exception:
            logger.exception("Proxy maintenance failed")
        finally:
            db.close()
        stop_event.wait(_PROXY_MAINTENANCE_INTERVAL_SECONDS)


@app.get("/health")
def health() -> dict:
    return {"status": "ok"}


api_prefix = "/api/v1"
app.include_router(webhook_router)
app.include_router(public_router, prefix=api_prefix)
app.include_router(admin_router, prefix=api_prefix)
app.include_router(internal_router, prefix=api_prefix)
