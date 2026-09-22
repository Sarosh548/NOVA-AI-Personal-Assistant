from datetime import datetime, timezone

import pytest
from fastapi.testclient import TestClient

import main
from api.auth import get_current_auth_context
from api.reminders import get_reminder_service


class FakeIdempotencyService:
    def __init__(self):
        self.claims = []
        self.completed = []
        self.failed = []

    def claim_or_replay(
        self,
        *,
        user_id,
        endpoint,
        idempotency_key,
        request_hash,
    ):
        self.claims.append({
            "user_id": user_id,
            "endpoint": endpoint,
            "idempotency_key": idempotency_key,
            "request_hash": request_hash,
        })
        return {
            "status": "claimed",
            "record_id": 1,
            "claim_token": "claim-token",
        }

    def complete(
        self,
        *,
        record_id,
        claim_token,
        response_status,
        response_body,
    ):
        self.completed.append({
            "record_id": record_id,
            "claim_token": claim_token,
            "response_status": response_status,
            "response_body": response_body,
        })
        return True

    def fail(
        self,
        *,
        record_id,
        claim_token,
        error,
    ):
        self.failed.append({
            "record_id": record_id,
            "claim_token": claim_token,
            "error": error,
        })
        return True


class FakeReminderService:
    def __init__(self):
        self.created = []
        self.list_calls = []
        self.update_calls = []
        self.complete_calls = []
        self.cancel_calls = []
        self.delete_calls = []

    def create_reminder(
        self,
        *,
        user_id,
        title,
        reminder_time,
    ):
        self.created.append(
            {
                "user_id": user_id,
                "title": title,
                "reminder_time": reminder_time,
            }
        )

        return 301

    def get_pending_reminders(
        self,
        *,
        user_id,
    ):
        self.list_calls.append(
            {
                "user_id": user_id,
            }
        )

        return [
            {
                "id": 301,
                "title": "Submit CV",
                "reminder_time": datetime(
                    2030,
                    1,
                    1,
                    10,
                    0,
                ),
                "status": "pending",
            },
            {
                "id": 300,
                "title": "Review NOVA",
                "reminder_time": datetime(
                    2030,
                    1,
                    2,
                    10,
                    0,
                ),
                "status": "pending",
            },
        ]

    def update_reminder(
        self,
        *,
        reminder_id,
        user_id,
        title,
        reminder_time,
    ):
        self.update_calls.append(
            {
                "reminder_id": reminder_id,
                "user_id": user_id,
                "title": title,
                "reminder_time": reminder_time,
            }
        )

        return True

    def complete_reminder(
        self,
        *,
        reminder_id,
        user_id,
    ):
        self.complete_calls.append(
            {
                "reminder_id": reminder_id,
                "user_id": user_id,
            }
        )

        return True

    def cancel_reminder(
        self,
        *,
        reminder_id,
        user_id,
    ):
        self.cancel_calls.append(
            {
                "reminder_id": reminder_id,
                "user_id": user_id,
            }
        )

        return True

    def delete_reminder(
        self,
        *,
        reminder_id,
        user_id,
    ):
        self.delete_calls.append(
            {
                "reminder_id": reminder_id,
                "user_id": user_id,
            }
        )

        return True


def _authenticated_context():
    from types import SimpleNamespace

    return SimpleNamespace(
        user=SimpleNamespace(
            id="user-001",
        )
    )


@pytest.fixture
def authenticated_api():
    service = FakeReminderService()

    main.app.dependency_overrides[
        get_reminder_service
    ] = lambda: service

    main.app.dependency_overrides[
        get_current_auth_context
    ] = _authenticated_context

    client = TestClient(
        main.app
    )

    try:
        yield client, service

    finally:
        main.app.dependency_overrides.pop(
            get_reminder_service,
            None,
        )
        main.app.dependency_overrides.pop(
            get_current_auth_context,
            None,
        )


def test_reminder_endpoints_require_authentication():
    main.app.dependency_overrides.pop(
        get_current_auth_context,
        None,
    )

    client = TestClient(
        main.app
    )

    response = client.get(
        "/reminders"
    )

    assert response.status_code == 401


def test_create_reminder_uses_authenticated_identity(
    authenticated_api,
):
    client, service = authenticated_api

    reminder_time = (
        "2030-01-01T10:00:00+00:00"
    )

    response = client.post(
        "/reminders",
        json={
            "title": "Submit CV",
            "reminder_time": reminder_time,
            "user_id": "attacker-user",
        },
    )

    assert response.status_code == 201

    assert response.json() == {
        "id": 301
    }

    assert service.created == [
        {
            "user_id": "user-001",
            "title": "Submit CV",
            "reminder_time": datetime(
                2030,
                1,
                1,
                10,
                0,
                tzinfo=timezone.utc,
            ),
        }
    ]


def test_create_reminder_value_error_returns_400(
    authenticated_api,
):
    class RejectingReminderService(
        FakeReminderService
    ):
        def create_reminder(
            self,
            *,
            user_id,
            title,
            reminder_time,
        ):
            raise ValueError(
                "Reminder time must be in the future."
            )

    service = RejectingReminderService()

    main.app.dependency_overrides[
        get_reminder_service
    ] = lambda: service

    client, _ = authenticated_api

    response = client.post(
        "/reminders",
        json={
            "title": "Old reminder",
            "reminder_time": (
                "2020-01-01T10:00:00+00:00"
            ),
        },
    )

    assert response.status_code == 400

    assert response.json() == {
        "detail": (
            "Reminder time must be in the future."
        )
    }


def test_get_reminders_uses_authenticated_identity(
    authenticated_api,
):
    client, service = authenticated_api

    response = client.get(
        "/reminders"
    )

    assert response.status_code == 200

    assert response.json() == [
        {
            "id": 301,
            "title": "Submit CV",
            "reminder_time": (
                "2030-01-01T10:00:00"
            ),
            "status": "pending",
        },
        {
            "id": 300,
            "title": "Review NOVA",
            "reminder_time": (
                "2030-01-02T10:00:00"
            ),
            "status": "pending",
        },
    ]

    assert service.list_calls == [
        {
            "user_id": "user-001",
        }
    ]


def test_update_reminder_uses_authenticated_identity(
    authenticated_api,
):
    client, service = authenticated_api

    response = client.patch(
        "/reminders/301",
        json={
            "title": "Submit updated CV",
            "reminder_time": (
                "2030-01-03T12:00:00+00:00"
            ),
        },
    )

    assert response.status_code == 200

    assert response.json() == {
        "updated": True
    }

    assert service.update_calls == [
        {
            "reminder_id": 301,
            "user_id": "user-001",
            "title": "Submit updated CV",
            "reminder_time": datetime(
                2030,
                1,
                3,
                12,
                0,
                tzinfo=timezone.utc,
            ),
        }
    ]


def test_update_reminder_value_error_returns_400(
    authenticated_api,
):
    class RejectingReminderService(
        FakeReminderService
    ):
        def update_reminder(
            self,
            *,
            reminder_id,
            user_id,
            title,
            reminder_time,
        ):
            raise ValueError(
                "No reminder fields were provided "
                "for update."
            )

    service = RejectingReminderService()

    main.app.dependency_overrides[
        get_reminder_service
    ] = lambda: service

    client, _ = authenticated_api

    response = client.patch(
        "/reminders/301",
        json={},
    )

    assert response.status_code == 400

    assert response.json() == {
        "detail": (
            "No reminder fields were provided "
            "for update."
        )
    }


def test_update_reminder_missing_returns_404(
    authenticated_api,
):
    class MissingReminderService(
        FakeReminderService
    ):
        def update_reminder(
            self,
            *,
            reminder_id,
            user_id,
            title,
            reminder_time,
        ):
            return False

    service = MissingReminderService()

    main.app.dependency_overrides[
        get_reminder_service
    ] = lambda: service

    client, _ = authenticated_api

    response = client.patch(
        "/reminders/999",
        json={
            "title": "Missing",
        },
    )

    assert response.status_code == 404

    assert response.json() == {
        "detail": "Reminder not found."
    }


def test_complete_reminder_uses_authenticated_identity(
    authenticated_api,
):
    client, service = authenticated_api

    response = client.post(
        "/reminders/301/complete"
    )

    assert response.status_code == 200

    assert response.json() == {
        "action": "complete",
        "updated": True,
    }

    assert service.complete_calls == [
        {
            "reminder_id": 301,
            "user_id": "user-001",
        }
    ]


def test_cancel_reminder_uses_authenticated_identity(
    authenticated_api,
):
    client, service = authenticated_api

    response = client.post(
        "/reminders/301/cancel"
    )

    assert response.status_code == 200

    assert response.json() == {
        "action": "cancel",
        "updated": True,
    }

    assert service.cancel_calls == [
        {
            "reminder_id": 301,
            "user_id": "user-001",
        }
    ]


def test_delete_reminder_uses_authenticated_identity(
    authenticated_api,
):
    client, service = authenticated_api

    response = client.delete(
        "/reminders/301"
    )

    assert response.status_code == 204
    assert response.content == b""

    assert service.delete_calls == [
        {
            "reminder_id": 301,
            "user_id": "user-001",
        }
    ]


def test_complete_missing_reminder_returns_404(
    authenticated_api,
):
    class MissingReminderService(
        FakeReminderService
    ):
        def complete_reminder(
            self,
            *,
            reminder_id,
            user_id,
        ):
            return False

    service = MissingReminderService()

    main.app.dependency_overrides[
        get_reminder_service
    ] = lambda: service

    client, _ = authenticated_api

    response = client.post(
        "/reminders/999/complete"
    )

    assert response.status_code == 404

    assert response.json() == {
        "detail": "Reminder not found."
    }


def test_delete_missing_reminder_returns_404(
    authenticated_api,
):
    class MissingReminderService(
        FakeReminderService
    ):
        def delete_reminder(
            self,
            *,
            reminder_id,
            user_id,
        ):
            return False

    service = MissingReminderService()

    main.app.dependency_overrides[
        get_reminder_service
    ] = lambda: service

    client, _ = authenticated_api

    response = client.delete(
        "/reminders/999"
    )

    assert response.status_code == 404

    assert response.json() == {
        "detail": "Reminder not found."
    }

def test_create_reminder_idempotency_key_is_persisted(
    authenticated_api,
    monkeypatch,
):
    client, service = authenticated_api
    import api.reminders as reminder_module

    fake_idempotency = FakeIdempotencyService()
    monkeypatch.setattr(
        reminder_module,
        "idempotency_service",
        fake_idempotency,
    )

    response = client.post(
        "/reminders",
        headers={"Idempotency-Key": "reminder-create-1"},
        json={
            "title": "Submit CV",
            "reminder_time": "2030-01-01T10:00:00+00:00",
        },
    )

    assert response.status_code == 201
    assert response.json() == {"id": 301}
    assert len(fake_idempotency.claims) == 1
    assert fake_idempotency.claims[0]["endpoint"] == "/reminders"
    assert fake_idempotency.claims[0]["idempotency_key"] == "reminder-create-1"
    assert len(fake_idempotency.completed) == 1
    assert fake_idempotency.completed[0]["response_status"] == 201
    assert fake_idempotency.completed[0]["response_body"] == {"id": 301}


def test_create_reminder_idempotency_replay_does_not_create_again(
    authenticated_api,
    monkeypatch,
):
    client, service = authenticated_api
    import api.reminders as reminder_module

    class ReplayService(FakeIdempotencyService):
        def claim_or_replay(self, **kwargs):
            return {
                "status": "replay",
                "record_id": 1,
                "response_body": {"id": 888},
            }

    monkeypatch.setattr(
        reminder_module,
        "idempotency_service",
        ReplayService(),
    )

    response = client.post(
        "/reminders",
        headers={"Idempotency-Key": "reminder-create-replay"},
        json={
            "title": "Repeated reminder",
            "reminder_time": "2030-01-01T10:00:00+00:00",
        },
    )

    assert response.status_code == 201
    assert response.json() == {"id": 888}
    assert service.created == []


def test_create_reminder_idempotency_conflict_returns_409(
    authenticated_api,
    monkeypatch,
):
    client, service = authenticated_api
    import api.reminders as reminder_module

    class ConflictService(FakeIdempotencyService):
        def claim_or_replay(self, **kwargs):
            return {"status": "conflict", "record_id": 1}

    monkeypatch.setattr(
        reminder_module,
        "idempotency_service",
        ConflictService(),
    )

    response = client.post(
        "/reminders",
        headers={"Idempotency-Key": "reminder-create-conflict"},
        json={
            "title": "Conflict",
            "reminder_time": "2030-01-01T10:00:00+00:00",
        },
    )

    assert response.status_code == 409
    assert response.json()["detail"].startswith(
        "Idempotency-Key was already used"
    )
    assert service.created == []
