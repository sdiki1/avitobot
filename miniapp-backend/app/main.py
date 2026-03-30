from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app.config import settings
from app.database import SessionLocal
from app.routers.admin import router as admin_router
from app.routers.internal import router as internal_router
from app.routers.public import router as public_router
from app.services.bootstrap import init_db, seed_default_plans


app = FastAPI(title=settings.app_name)

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
    init_db()
    db = SessionLocal()
    try:
        seed_default_plans(db)
    finally:
        db.close()


@app.get("/health")
def health() -> dict:
    return {"status": "ok"}


api_prefix = "/api/v1"
app.include_router(public_router, prefix=api_prefix)
app.include_router(admin_router, prefix=api_prefix)
app.include_router(internal_router, prefix=api_prefix)
