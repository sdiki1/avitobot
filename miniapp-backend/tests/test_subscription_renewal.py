import os
import sys
import types
import unittest
from datetime import timedelta
from unittest.mock import patch

from sqlalchemy import create_engine, select
from sqlalchemy.orm import Session

os.environ.setdefault("DATABASE_URL", "sqlite+pysqlite:///:memory:")

# These tests do not call Redis or JWT. Supply only missing third-party modules
# so the real application modules can still be imported in a lightweight env.
try:
    import redis  # noqa: F401
except ModuleNotFoundError:
    redis_module = types.ModuleType("redis")
    redis_module.Redis = type("Redis", (), {})
    sys.modules["redis"] = redis_module

try:
    import jwt  # noqa: F401
except ModuleNotFoundError:
    jwt_module = types.ModuleType("jwt")
    jwt_module.encode = lambda *_args, **_kwargs: "test-token"
    jwt_module.decode = lambda *_args, **_kwargs: {}
    sys.modules["jwt"] = jwt_module

from app.database import Base
from app.models import Monitoring, Payment, TariffPlan, TelegramBot, User, UserSubscription
from app.routers.public import _finalize_subscription_payment
from app.services.helpers import get_monitoring_subscription_map, now_utc


class SubscriptionRenewalTest(unittest.TestCase):
    def setUp(self) -> None:
        self.engine = create_engine("sqlite+pysqlite:///:memory:")
        Base.metadata.create_all(self.engine)
        self.db = Session(self.engine)
        self.user = User(telegram_id=10001, referral_balance_rub=0)
        self.plan = TariffPlan(
            name="Стандарт · 30 дней",
            plan_format="standard",
            duration_label="30 дней",
            links_limit=1,
            duration_days=30,
            price_rub=500,
            is_active=True,
        )
        self.primary_bot = TelegramBot(
            name="Основной", bot_token="primary-token", is_active=True, is_primary=True
        )
        self.first_worker = TelegramBot(
            name="Бот 1", bot_token="worker-token-1", is_active=True, is_primary=False
        )
        self.second_worker = TelegramBot(
            name="Бот 2", bot_token="worker-token-2", is_active=True, is_primary=False
        )
        self.db.add_all([self.user, self.plan, self.primary_bot, self.first_worker, self.second_worker])
        self.db.commit()

    def tearDown(self) -> None:
        self.db.close()
        self.engine.dispose()

    def finalize(self, payment: Payment) -> UserSubscription:
        self.db.add(payment)
        self.db.commit()
        with (
            patch("app.routers.public.send_subscription_assigned_bot_message", return_value=True),
            patch("app.routers.public.send_admin_event_message", return_value=True),
        ):
            return _finalize_subscription_payment(
                db=self.db,
                user=self.user,
                plan=self.plan,
                payment=payment,
            )

    def test_expired_renewal_reuses_subscription_and_assigns_first_bot(self) -> None:
        expired = UserSubscription(
            user_id=self.user.id,
            plan_id=self.plan.id,
            status="active",
            amount_paid=500,
            started_at=now_utc() - timedelta(days=60),
            ends_at=now_utc() - timedelta(days=30),
        )
        self.db.add(expired)
        self.db.flush()
        monitoring = Monitoring(
            user_id=self.user.id,
            subscription_id=expired.id,
            bot_id=None,
            url="https://www.avito.ru/test",
            title="Старый мониторинг",
            is_active=False,
            link_configured=True,
        )
        self.db.add(monitoring)
        self.db.commit()

        payment = Payment(
            user_id=self.user.id,
            plan_id=self.plan.id,
            amount_rub=500,
            status="completed",
            provider="test",
            payload={
                "monitoring_id": monitoring.id,
                "target_total_slots": 1,
                "create_new_monitoring": False,
            },
        )
        renewed = self.finalize(payment)
        self.db.refresh(monitoring)

        self.assertEqual(renewed.id, expired.id)
        self.assertEqual(monitoring.subscription_id, expired.id)
        self.assertEqual(monitoring.bot_id, self.first_worker.id)
        self.assertGreater(renewed.ends_at.replace(tzinfo=None), now_utc().replace(tzinfo=None))
        self.assertEqual(
            self.db.scalar(select(Monitoring).where(Monitoring.user_id == self.user.id)).id,
            monitoring.id,
        )

    def test_renewal_does_not_move_subscription_to_another_monitoring(self) -> None:
        first_sub = UserSubscription(
            user_id=self.user.id,
            plan_id=self.plan.id,
            status="active",
            amount_paid=500,
            started_at=now_utc(),
            ends_at=now_utc() + timedelta(days=20),
        )
        second_sub = UserSubscription(
            user_id=self.user.id,
            plan_id=self.plan.id,
            status="active",
            amount_paid=500,
            started_at=now_utc(),
            ends_at=now_utc() + timedelta(days=10),
        )
        self.db.add_all([first_sub, second_sub])
        self.db.flush()
        first_monitoring = Monitoring(
            user_id=self.user.id,
            subscription_id=first_sub.id,
            bot_id=self.first_worker.id,
            url="https://www.avito.ru/1",
            title="Первый",
            is_active=False,
            link_configured=True,
        )
        second_monitoring = Monitoring(
            user_id=self.user.id,
            subscription_id=second_sub.id,
            bot_id=self.second_worker.id,
            url="https://www.avito.ru/2",
            title="Второй",
            is_active=False,
            link_configured=True,
        )
        self.db.add_all([first_monitoring, second_monitoring])
        self.db.commit()

        payment = Payment(
            user_id=self.user.id,
            plan_id=self.plan.id,
            amount_rub=500,
            status="completed",
            provider="test",
            payload={
                "monitoring_id": second_monitoring.id,
                "target_total_slots": 2,
                "create_new_monitoring": False,
            },
        )
        renewed = self.finalize(payment)
        mapping = get_monitoring_subscription_map(self.db, self.user.id)

        self.assertEqual(renewed.id, second_sub.id)
        self.assertEqual(mapping[first_monitoring.id]["subscription_id"], first_sub.id)
        self.assertEqual(mapping[second_monitoring.id]["subscription_id"], second_sub.id)

    def test_new_purchase_after_expiration_uses_first_bot(self) -> None:
        payment = Payment(
            user_id=self.user.id,
            plan_id=self.plan.id,
            amount_rub=500,
            status="completed",
            provider="test",
            payload={"target_total_slots": 1, "create_new_monitoring": True},
        )
        subscription = self.finalize(payment)
        monitoring = self.db.scalar(
            select(Monitoring).where(Monitoring.subscription_id == subscription.id)
        )

        self.assertIsNotNone(monitoring)
        self.assertEqual(monitoring.bot_id, self.first_worker.id)


if __name__ == "__main__":
    unittest.main()
