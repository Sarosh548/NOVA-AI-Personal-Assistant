from __future__ import annotations

from api import auth as auth_api
import main
from services.notification_service import NotificationChannelRegistry, NotificationService


class FakeEmailChannel:
    def __init__(self):
        self.messages = []

    def send_email(self, **kwargs):
        self.messages.append(kwargs)
        return True


class FakeGoogleMailService:
    def send_email(self, **kwargs):
        raise AssertionError("Transactional auth mail must not use a user Gmail mailbox")


class FakeSettings:
    auth_jwt_secret_key = "auth-service-test-master-secret-with-at-least-32-chars"


def test_runtime_auth_services_use_smtp_and_distinct_derived_secrets(monkeypatch):
    registry = NotificationChannelRegistry()
    smtp = FakeEmailChannel()
    registry.register("email", smtp)
    normal_notifications = NotificationService(
        channel_registry=registry,
        default_channel="email",
        google_mail_service=FakeGoogleMailService(),
    )
    monkeypatch.setattr(main, "notification_service", normal_notifications)
    monkeypatch.setattr(main, "get_settings", lambda: FakeSettings())
    monkeypatch.setattr(auth_api, "email_verification_service", None)
    monkeypatch.setattr(auth_api, "password_reset_service", None)

    auth_notifications = main.configure_runtime_auth_services()

    assert auth_notifications is not None
    assert auth_notifications is not normal_notifications
    assert auth_notifications.channel_registry is registry
    assert auth_notifications.google_mail_service is None
    assert auth_api.email_verification_service is not None
    assert auth_api.password_reset_service is not None
    verification_key = auth_api.email_verification_service.secret_key
    reset_key = auth_api.password_reset_service.secret_key
    assert verification_key != FakeSettings.auth_jwt_secret_key
    assert reset_key != FakeSettings.auth_jwt_secret_key
    assert verification_key != reset_key

    assert auth_notifications.send_email(
        user_id="unverified-user",
        to="qa@example.com",
        subject="Verify your NOVA email",
        body="QA code",
    ) is True
    assert len(smtp.messages) == 1
    assert smtp.messages[0]["to"] == "qa@example.com"


def test_runtime_auth_services_remain_unavailable_without_smtp(monkeypatch):
    normal_notifications = NotificationService()
    monkeypatch.setattr(main, "notification_service", normal_notifications)
    monkeypatch.setattr(auth_api, "email_verification_service", object())
    monkeypatch.setattr(auth_api, "password_reset_service", object())

    result = main.configure_runtime_auth_services()

    assert result is None
    assert auth_api.email_verification_service is None
    assert auth_api.password_reset_service is None
