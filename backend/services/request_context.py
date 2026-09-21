from __future__ import annotations

from contextvars import ContextVar, Token
import re

from uuid import uuid4


_REQUEST_ID: ContextVar[str | None] = ContextVar(
    "nova_request_id",
    default=None,
)

_SAFE_REQUEST_ID = re.compile(
    r"^[A-Za-z0-9._:-]{1,128}$"
)


def generate_request_id() -> str:
    return uuid4().hex


def normalize_request_id(
    value: str | None,
) -> str:
    if value is not None:
        normalized = str(value).strip()

        if _SAFE_REQUEST_ID.fullmatch(
            normalized
        ):
            return normalized

    return generate_request_id()


def set_request_id(
    request_id: str,
) -> Token:
    return _REQUEST_ID.set(
        request_id
    )


def reset_request_id(
    token: Token,
) -> None:
    _REQUEST_ID.reset(
        token
    )


def get_request_id() -> str | None:
    return _REQUEST_ID.get()
