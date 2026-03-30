from fastapi import Header, HTTPException, status

from app.config import settings


def require_admin_token(x_admin_token: str | None = Header(default=None)) -> None:
    if x_admin_token != settings.admin_api_token:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Invalid admin token")


def require_internal_token(x_internal_token: str | None = Header(default=None)) -> None:
    if x_internal_token != settings.internal_api_token:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Invalid internal token")
