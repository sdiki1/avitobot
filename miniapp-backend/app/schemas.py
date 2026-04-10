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
    referral_code: str | None = None
    referral_balance_rub: int = 0

    class Config:
        from_attributes = True


class TelegramAuthResolveResponse(BaseModel):
    telegram_id: int
    user: UserResponse


class TelegramBotBase(BaseModel):
    name: str = Field(min_length=2, max_length=255)
    is_active: bool = True
    is_primary: bool = False


class TelegramBotCreate(TelegramBotBase):
    bot_token: str = Field(min_length=10, max_length=255)


class TelegramBotUpdate(BaseModel):
    name: str | None = Field(default=None, min_length=2, max_length=255)
    bot_token: str | None = Field(default=None, min_length=10, max_length=255)
    telegram_bot_id: int | None = None
    bot_username: str | None = None
    is_active: bool | None = None
    is_primary: bool | None = None


class TelegramBotResponse(TelegramBotBase):
    id: int
    telegram_bot_id: int | None = None
    bot_username: str | None = None
    bot_link: str | None = None
    created_at: datetime
    updated_at: datetime

    class Config:
        from_attributes = True


class BotReference(BaseModel):
    id: int
    name: str
    bot_username: str | None = None
    bot_link: str | None = None


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
    url: str | None = None
    title: str | None = None
    keywords_white: list[str] = Field(default_factory=list)
    keywords_black: list[str] = Field(default_factory=list)
    min_price: int | None = None
    max_price: int | None = None
    geo: str | None = None


class MonitoringPurchaseRequest(BaseModel):
    telegram_id: int
    title: str | None = None
    url: str | None = None


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
    link_configured: bool
    last_checked_at: datetime | None = None
    bot: BotReference | None = None


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


class PurchaseSubscriptionRequest(BaseModel):
    telegram_id: int
    plan_id: int


class PurchaseSubscriptionResponse(BaseModel):
    ok: bool
    subscription_id: int
    user_id: int
    plan_id: int
    ends_at: datetime
    is_trial: bool = False


class OnboardingTrialRequest(BaseModel):
    telegram_id: int


class OnboardingTrialResponse(BaseModel):
    granted: bool
    days: int
    ends_at: datetime | None = None


class TrialSettingsResponse(BaseModel):
    trial_days: int = Field(ge=0)


class TrialSettingsUpdate(BaseModel):
    trial_days: int = Field(ge=0)


class MiniAppInfoLink(BaseModel):
    key: str
    title: str
    url: str


class MiniAppContentResponse(BaseModel):
    support_title: str
    support_url: str
    faq_title: str
    faq_url: str
    news_title: str
    news_url: str
    terms_title: str
    terms_url: str
    privacy_title: str
    privacy_url: str
    subscriptions_title: str
    subscriptions_hint: str
    profile_title: str
    info_links: list[MiniAppInfoLink] = Field(default_factory=list)


class MiniAppContentUpdate(BaseModel):
    support_title: str = Field(min_length=1, max_length=120)
    support_url: str = Field(min_length=1, max_length=512)
    faq_title: str = Field(min_length=1, max_length=120)
    faq_url: str = Field(min_length=1, max_length=512)
    news_title: str = Field(min_length=1, max_length=120)
    news_url: str = Field(min_length=1, max_length=512)
    terms_title: str = Field(min_length=1, max_length=120)
    terms_url: str = Field(min_length=1, max_length=512)
    privacy_title: str = Field(min_length=1, max_length=120)
    privacy_url: str = Field(min_length=1, max_length=512)
    subscriptions_title: str = Field(min_length=1, max_length=120)
    subscriptions_hint: str = Field(min_length=1, max_length=300)
    profile_title: str = Field(min_length=1, max_length=120)


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
    bot_id: int | None = None
    telegram_bot_id: int | None = None
    monitoring_id: int
    message: str


class InternalBotConfigResponse(BaseModel):
    id: int
    name: str
    bot_token: str
    is_primary: bool = False
    telegram_bot_id: int | None = None
    bot_username: str | None = None


class InternalBotLookupResponse(BaseModel):
    monitoring_id: int
    title: str | None = None
    url: str
    is_active: bool
    link_configured: bool


class InternalBotSyncRequest(BaseModel):
    telegram_bot_id: int
    bot_username: str | None = None


class InternalBotCommandRequest(BaseModel):
    telegram_id: int
    bot_id: int
    url: str | None = None
