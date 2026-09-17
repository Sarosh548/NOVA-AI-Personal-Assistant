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


def _prepare_database(monkeypatch):
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


def _create_approved_confirmation(
    service,
):
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

    approved = (
        service.approve_confirmation(
            user_id="test-user",
            confirmation_id=confirmation_id,
        )
    )

    assert approved is not None
    assert approved["status"] == "approved"

    return confirmation_id


def test_approved_confirmation_can_be_claimed_once(
    monkeypatch,
):
    test_engine = _prepare_database(
        monkeypatch
    )

    try:
        service = ConfirmationService()

        confirmation_id = (
            _create_approved_confirmation(
                service
            )
        )

        first_claim = (
            service.claim_confirmation(
                user_id="test-user",
                confirmation_id=confirmation_id,
            )
        )

        assert first_claim is not None
        assert first_claim["status"] == "processing"

        second_claim = (
            service.claim_confirmation(
                user_id="test-user",
                confirmation_id=confirmation_id,
            )
        )

        assert second_claim is None

    finally:
        test_engine.dispose()


def test_consumed_confirmation_cannot_be_claimed_again(
    monkeypatch,
):
    test_engine = _prepare_database(
        monkeypatch
    )

    try:
        service = ConfirmationService()

        confirmation_id = (
            _create_approved_confirmation(
                service
            )
        )

        claimed = (
            service.claim_confirmation(
                user_id="test-user",
                confirmation_id=confirmation_id,
            )
        )

        assert claimed is not None

        finished = (
            service.finish_confirmation(
                user_id="test-user",
                confirmation_id=confirmation_id,
                success=True,
            )
        )

        assert finished is not None
        assert finished["status"] == "consumed"

        replay = (
            service.claim_confirmation(
                user_id="test-user",
                confirmation_id=confirmation_id,
            )
        )

        assert replay is None

    finally:
        test_engine.dispose()


def test_failed_confirmation_cannot_be_claimed_again(
    monkeypatch,
):
    test_engine = _prepare_database(
        monkeypatch
    )

    try:
        service = ConfirmationService()

        confirmation_id = (
            _create_approved_confirmation(
                service
            )
        )

        claimed = (
            service.claim_confirmation(
                user_id="test-user",
                confirmation_id=confirmation_id,
            )
        )

        assert claimed is not None

        finished = (
            service.finish_confirmation(
                user_id="test-user",
                confirmation_id=confirmation_id,
                success=False,
            )
        )

        assert finished is not None
        assert finished["status"] == "failed"

        replay = (
            service.claim_confirmation(
                user_id="test-user",
                confirmation_id=confirmation_id,
            )
        )

        assert replay is None

    finally:
        test_engine.dispose()


def test_unapproved_confirmation_cannot_be_claimed(
    monkeypatch,
):
    test_engine = _prepare_database(
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

        claim = (
            service.claim_confirmation(
                user_id="test-user",
                confirmation_id=confirmation_id,
            )
        )

        assert claim is None

    finally:
        test_engine.dispose()


def test_finish_confirmation_requires_processing_state(
    monkeypatch,
):
    test_engine = _prepare_database(
        monkeypatch
    )

    try:
        service = ConfirmationService()

        confirmation_id = (
            _create_approved_confirmation(
                service
            )
        )

        result = (
            service.finish_confirmation(
                user_id="test-user",
                confirmation_id=confirmation_id,
                success=True,
            )
        )

        assert result is not None
        assert result["status"] == "approved"

    finally:
        test_engine.dispose()