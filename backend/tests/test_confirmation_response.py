from services.confirmation_service import (
    ConfirmationService,
)


def test_parse_approval_yes():
    service = ConfirmationService()

    assert (
        service.parse_response("yes")
        == "approve"
    )


def test_parse_approval_go_ahead():
    service = ConfirmationService()

    assert (
        service.parse_response("Go ahead")
        == "approve"
    )


def test_parse_approval_roman_urdu():
    service = ConfirmationService()

    assert (
        service.parse_response("haan")
        == "approve"
    )


def test_parse_rejection_no():
    service = ConfirmationService()

    assert (
        service.parse_response("no")
        == "reject"
    )


def test_parse_rejection_cancel():
    service = ConfirmationService()

    assert (
        service.parse_response("cancel")
        == "reject"
    )


def test_parse_rejection_roman_urdu():
    service = ConfirmationService()

    assert (
        service.parse_response("nahi")
        == "reject"
    )


def test_parse_ambiguous_message_returns_none():
    service = ConfirmationService()

    assert (
        service.parse_response(
            "Can you tell me what is going on?"
        )
        is None
    )


def test_parse_empty_message_returns_none():
    service = ConfirmationService()

    assert (
        service.parse_response("")
        is None
    )