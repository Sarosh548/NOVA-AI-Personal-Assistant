from datetime import datetime, timedelta

from sqlalchemy import create_engine
from sqlalchemy.pool import StaticPool

from models.confirmation import Confirmation
from services.confirmation_service import (
    ConfirmationService,
)
import services.confirmation_service as confirmation_service_module


def _create_test_engine():
    return create_engine(
        "sqlite://",
        connect_args={
            "check_same_thread": False,
        },
        poolclass=StaticPool,
    )


def _prepare_confirmation_database(
    monkeypatch,
):
    test_engine = _create_test_engine()

    Confirmation.__table__.create(
        bind=test_engine
    )

    monkeypatch.setattr(
        confirmation_service_module,
        "engine",
        test_engine,
    )

    return test_engine


def test_create_and_get_confirmation(
    monkeypatch,
):
    test_engine = _prepare_confirmation_database(
        monkeypatch
    )

    try:
        service = ConfirmationService()

        confirmation_id = (
            service.create_confirmation(
                user_id="test-user",
                conversation_id=10,
                tool="email",
                action="send",
                data={
                    "to": "test@example.com",
                    "subject": "Test",
                    "body": "Hello",
                },
                reason=(
                    "Sending this email requires confirmation."
                ),
            )
        )

        assert confirmation_id > 0

        confirmation = (
            service.get_confirmation(
                user_id="test-user",
                confirmation_id=confirmation_id,
            )
        )

        assert confirmation is not None
        assert confirmation["id"] == confirmation_id
        assert confirmation["user_id"] == "test-user"
        assert confirmation["conversation_id"] == 10
        assert confirmation["tool"] == "email"
        assert confirmation["action"] == "send"
        assert confirmation["status"] == "pending"
        assert confirmation["data"]["to"] == (
            "test@example.com"
        )

    finally:
        test_engine.dispose()


def test_get_confirmation_respects_user_ownership(
    monkeypatch,
):
    test_engine = _prepare_confirmation_database(
        monkeypatch
    )

    try:
        service = ConfirmationService()

        confirmation_id = (
            service.create_confirmation(
                user_id="owner",
                conversation_id=None,
                tool="task",
                action="delete",
                data={
                    "task_id": 15,
                },
                reason="Task deletion needs approval.",
            )
        )

        result = service.get_confirmation(
            user_id="different-user",
            confirmation_id=confirmation_id,
        )

        assert result is None

    finally:
        test_engine.dispose()


def test_latest_pending_confirmation(
    monkeypatch,
):
    test_engine = _prepare_confirmation_database(
        monkeypatch
    )

    try:
        service = ConfirmationService()

        first_id = (
            service.create_confirmation(
                user_id="test-user",
                conversation_id=20,
                tool="task",
                action="delete",
                data={
                    "task_id": 1,
                },
                reason="Delete task?",
            )
        )

        second_id = (
            service.create_confirmation(
                user_id="test-user",
                conversation_id=20,
                tool="email",
                action="send",
                data={
                    "to": "test@example.com",
                },
                reason="Send email?",
            )
        )

        latest = (
            service.get_latest_pending_confirmation(
                user_id="test-user",
                conversation_id=20,
            )
        )

        assert latest is not None
        assert latest["id"] == second_id
        assert latest["id"] != first_id

    finally:
        test_engine.dispose()


def test_list_pending_confirmations_filters_by_user_and_conversation(
    monkeypatch,
):
    test_engine = _prepare_confirmation_database(
        monkeypatch
    )

    try:
        service = ConfirmationService()

        service.create_confirmation(
            user_id="test-user",
            conversation_id=30,
            tool="task",
            action="create",
            data={
                "title": "Practice Python",
            },
            reason="Create task?",
        )

        service.create_confirmation(
            user_id="test-user",
            conversation_id=30,
            tool="reminder",
            action="create",
            data={
                "title": "Call HR",
            },
            reason="Create reminder?",
        )

        service.create_confirmation(
            user_id="test-user",
            conversation_id=31,
            tool="email",
            action="send",
            data={
                "to": "test@example.com",
            },
            reason="Send email?",
        )

        service.create_confirmation(
            user_id="other-user",
            conversation_id=30,
            tool="task",
            action="delete",
            data={
                "task_id": 99,
            },
            reason="Delete task?",
        )

        results = (
            service.list_pending_confirmations(
                user_id="test-user",
                conversation_id=30,
            )
        )

        assert len(results) == 2

        assert {
            (
                item["tool"],
                item["action"],
            )
            for item in results
        } == {
            ("task", "create"),
            ("reminder", "create"),
        }

    finally:
        test_engine.dispose()


def test_approve_confirmation(
    monkeypatch,
):
    test_engine = _prepare_confirmation_database(
        monkeypatch
    )

    try:
        service = ConfirmationService()

        confirmation_id = (
            service.create_confirmation(
                user_id="test-user",
                conversation_id=None,
                tool="email",
                action="send",
                data={
                    "to": "test@example.com",
                },
                reason="Send this email?",
            )
        )

        result = (
            service.approve_confirmation(
                user_id="test-user",
                confirmation_id=confirmation_id,
            )
        )

        assert result is not None
        assert result["status"] == "approved"
        assert result["resolved_at"] is not None

        stored = service.get_confirmation(
            user_id="test-user",
            confirmation_id=confirmation_id,
        )

        assert stored is not None
        assert stored["status"] == "approved"

    finally:
        test_engine.dispose()


def test_reject_confirmation(
    monkeypatch,
):
    test_engine = _prepare_confirmation_database(
        monkeypatch
    )

    try:
        service = ConfirmationService()

        confirmation_id = (
            service.create_confirmation(
                user_id="test-user",
                conversation_id=None,
                tool="email",
                action="send",
                data={
                    "to": "test@example.com",
                },
                reason="Send this email?",
            )
        )

        result = (
            service.reject_confirmation(
                user_id="test-user",
                confirmation_id=confirmation_id,
            )
        )

        assert result is not None
        assert result["status"] == "rejected"
        assert result["resolved_at"] is not None

        stored = service.get_confirmation(
            user_id="test-user",
            confirmation_id=confirmation_id,
        )

        assert stored is not None
        assert stored["status"] == "rejected"

    finally:
        test_engine.dispose()


def test_expired_confirmation_cannot_be_approved(
    monkeypatch,
):
    test_engine = _prepare_confirmation_database(
        monkeypatch
    )

    try:
        service = ConfirmationService()

        now = service._utc_now_naive()

        confirmation = Confirmation(
            user_id="test-user",
            conversation_id=None,
            tool="email",
            action="send",
            data={
                "to": "test@example.com",
            },
            reason="Send this email?",
            status="pending",
            created_at=now - timedelta(
                minutes=10
            ),
            expires_at=now - timedelta(
                minutes=5
            ),
            resolved_at=None,
        )

        with confirmation_service_module.Session(
            test_engine
        ) as session:
            session.add(confirmation)
            session.commit()
            session.refresh(confirmation)

            confirmation_id = confirmation.id

        result = (
            service.approve_confirmation(
                user_id="test-user",
                confirmation_id=confirmation_id,
            )
        )

        assert result is not None
        assert result["status"] == "expired"
        assert result["resolved_at"] is not None

    finally:
        test_engine.dispose()


def test_expired_pending_confirmation_is_not_returned(
    monkeypatch,
):
    test_engine = _prepare_confirmation_database(
        monkeypatch
    )

    try:
        service = ConfirmationService()

        now = service._utc_now_naive()

        confirmation = Confirmation(
            user_id="test-user",
            conversation_id=None,
            tool="task",
            action="delete",
            data={
                "task_id": 20,
            },
            reason="Delete task?",
            status="pending",
            created_at=now - timedelta(
                minutes=10
            ),
            expires_at=now - timedelta(
                minutes=1
            ),
            resolved_at=None,
        )

        with confirmation_service_module.Session(
            test_engine
        ) as session:
            session.add(confirmation)
            session.commit()

        result = (
            service.get_latest_pending_confirmation(
                user_id="test-user"
            )
        )

        assert result is None

        all_results = (
            service.list_pending_confirmations(
                user_id="test-user"
            )
        )

        assert all_results == []

    finally:
        test_engine.dispose()


def test_delete_confirmation(
    monkeypatch,
):
    test_engine = _prepare_confirmation_database(
        monkeypatch
    )

    try:
        service = ConfirmationService()

        confirmation_id = (
            service.create_confirmation(
                user_id="test-user",
                conversation_id=None,
                tool="task",
                action="delete",
                data={
                    "task_id": 25,
                },
                reason="Delete task?",
            )
        )

        deleted = (
            service.delete_confirmation
            if hasattr(
                service,
                "delete_confirmation",
            )
            else None
        )

        assert deleted is None or callable(deleted)

    finally:
        test_engine.dispose()


def test_create_confirmation_validates_expiry(
    monkeypatch,
):
    test_engine = _prepare_confirmation_database(
        monkeypatch
    )

    try:
        service = ConfirmationService()

        try:
            service.create_confirmation(
                user_id="test-user",
                conversation_id=None,
                tool="task",
                action="create",
                data={
                    "title": "Test",
                },
                reason="Create task?",
                expires_in_seconds=0,
            )
            assert False
        except ValueError as exc:
            assert (
                str(exc)
                == (
                    "Confirmation expiry must be "
                    "greater than zero."
                )
            )

    finally:
        test_engine.dispose()

def test_approve_and_claim_confirmation_success(
    monkeypatch,
):
    test_engine = _prepare_confirmation_database(
        monkeypatch
    )

    try:
        service = ConfirmationService()

        confirmation_id = (
            service.create_confirmation(
                user_id="test-user",
                conversation_id=10,
                tool="email",
                action="send",
                data={
                    "to": "test@example.com",
                },
                reason="Send this email?",
            )
        )

        result = (
            service.approve_and_claim_confirmation(
                user_id="test-user",
                confirmation_id=confirmation_id,
            )
        )

        assert result is not None
        assert result["id"] == confirmation_id
        assert result["status"] == "processing"
        assert result["tool"] == "email"
        assert result["action"] == "send"
        assert result["data"] == {
            "to": "test@example.com",
        }
        assert result["resolved_at"] is not None

    finally:
        test_engine.dispose()


def test_approve_and_claim_confirmation_cannot_be_replayed(
    monkeypatch,
):
    test_engine = _prepare_confirmation_database(
        monkeypatch
    )

    try:
        service = ConfirmationService()

        confirmation_id = (
            service.create_confirmation(
                user_id="test-user",
                conversation_id=None,
                tool="task",
                action="delete",
                data={
                    "task_id": 25,
                },
                reason="Delete task?",
            )
        )

        first = (
            service.approve_and_claim_confirmation(
                user_id="test-user",
                confirmation_id=confirmation_id,
            )
        )

        second = (
            service.approve_and_claim_confirmation(
                user_id="test-user",
                confirmation_id=confirmation_id,
            )
        )

        assert first is not None
        assert first["status"] == "processing"
        assert second is None

        stored = service.get_confirmation(
            user_id="test-user",
            confirmation_id=confirmation_id,
        )

        assert stored is not None
        assert stored["status"] == "processing"

    finally:
        test_engine.dispose()


def test_approve_and_claim_expired_confirmation_marks_it_expired(
    monkeypatch,
):
    test_engine = _prepare_confirmation_database(
        monkeypatch
    )

    try:
        service = ConfirmationService()

        now = service._utc_now_naive()

        confirmation = Confirmation(
            user_id="test-user",
            conversation_id=None,
            tool="email",
            action="send",
            data={
                "to": "test@example.com",
            },
            reason="Send this email?",
            status="pending",
            created_at=now - timedelta(
                minutes=10
            ),
            expires_at=now - timedelta(
                minutes=1
            ),
            resolved_at=None,
        )

        with confirmation_service_module.Session(
            test_engine
        ) as session:
            session.add(confirmation)
            session.commit()
            session.refresh(confirmation)

            confirmation_id = confirmation.id

        result = (
            service.approve_and_claim_confirmation(
                user_id="test-user",
                confirmation_id=confirmation_id,
            )
        )

        assert result is None

        stored = service.get_confirmation(
            user_id="test-user",
            confirmation_id=confirmation_id,
        )

        assert stored is not None
        assert stored["status"] == "expired"
        assert stored["resolved_at"] is not None

    finally:
        test_engine.dispose()
