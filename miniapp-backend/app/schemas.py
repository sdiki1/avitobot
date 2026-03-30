from datetime import datetime

from pydantic import BaseModel, Field


class TelegramAuthRequest(BaseModel):
    telegram_id: int
    username: str | None = None
    full_name: str | None = None


class UserResponse(BaseModel):
    id: int
    telegram_id: int
    username: str | None = None
    full_name: str | None = None

    class Config:
        from_attributes = True


class TariffPlanBase(BaseModel):
    name: str = Field(min_length=2, max_length=255)
    description: str | None = None
    links_limit: int = Field(gt=0)
    duration_days: int = Field(gt=0)
    price_rub: int = Field(ge=0)
    is_active: bool = True


class TariffPlanCreate(TariffPlanBase):
    pass


class TariffPlanUpdate(BaseModel):
    name: str | None = None
    description: str | None = None
    links_limit: int | None = Field(default=None, gt=0)
    duration_days: int | None = Field(default=None, gt=0)
    price_rub: int | None = Field(default=None, ge=0)
    is_active: bool | None = None


class TariffPlanResponse(TariffPlanBase):
    id: int

    class Config:
        from_attributes = True


class MonitoringCreate(BaseModel):
    telegram_id: int
    url: str
    title: str | None = None
    keywords_white: list[str] = Field(default_factory=list)
    keywords_black: list[str] = Field(default_factory=list)
    min_price: int | None = None
    max_price: int | None = None
    geo: str | None = None


class MonitoringResponse(BaseModel):
    id: int
    url: str
    title: str | None = None
    keywords_white: list[str] = Field(default_factory=list)
    keywords_black: list[str] = Field(default_factory=list)
    min_price: int | None = None
    max_price: int | None = None
    geo: str | None = None
    is_active: bool
    last_checked_at: datetime | None = None


class MonitoringItemResponse(BaseModel):
    id: int
    avito_ad_id: str
    title: str
    url: str
    price_rub: int | None = None
    location: str | None = None
    published_at: datetime | None = None
    first_seen_at: datetime


class ProxyCreate(BaseModel):
    name: str
    proxy_url: str
    change_ip_url: str | None = None
    is_active: bool = True


class ProxyUpdate(BaseModel):
    name: str | None = None
    proxy_url: str | None = None
    change_ip_url: str | None = None
    is_active: bool | None = None


class ProxyResponse(BaseModel):
    id: int
    name: str
    proxy_url: str
    change_ip_url: str | None = None
    is_active: bool
    fail_count: int

    class Config:
        from_attributes = True


class PaymentCreate(BaseModel):
    telegram_id: int
    plan_id: int
    amount_rub: int
    provider: str = "manual"


class PaymentResponse(BaseModel):
    id: int
    user_id: int
    plan_id: int | None = None
    amount_rub: int
    status: str
    provider: str
    created_at: datetime

    class Config:
        from_attributes = True


class ActivateSubscriptionRequest(BaseModel):
    telegram_id: int
    plan_id: int


class InternalParsedItem(BaseModel):
    avito_ad_id: str
    title: str
    url: str
    price_rub: int | None = None
    location: str | None = None
    published_at: datetime | None = None
    raw_json: dict | None = None


class InternalScanPayload(BaseModel):
    items: list[InternalParsedItem]


class NotificationResponse(BaseModel):
    id: int
    message: str
    created_at: datetime
    monitoring_id: int


class InternalNotificationResponse(BaseModel):
    id: int
    telegram_id: int
    message: str
