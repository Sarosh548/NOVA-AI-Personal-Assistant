from __future__ import annotations

from datetime import datetime, timezone
from uuid import uuid4

from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from database.connection import engine as default_engine
from models.user import User


class UserService:
    """
    Manage NOVA user identity records.

    Authentication credentials, external identity providers,
    sessions, and authorization are intentionally handled by
    separate layers.
    """

    MAX_USER_ID_LENGTH = 100
    MAX_DISPLAY_NAME_LENGTH = 200

    def __init__(self, engine=None):
        self.engine = engine or default_engine

    @staticmethod
    def _utc_now_naive() -> datetime:
        return datetime.now(
            timezone.utc
        ).replace(
            tzinfo=None
        )

    @classmethod
    def _validate_user_id(
        cls,
        user_id: str,
    ) -> str:
        normalized = str(
            user_id
        ).strip()

        if not normalized:
            raise ValueError(
                "user_id cannot be empty."
            )

        if len(normalized) > cls.MAX_USER_ID_LENGTH:
            raise ValueError(
                "user_id cannot exceed 100 characters."
            )

        return normalized

    @classmethod
    def _validate_display_name(
        cls,
        display_name: str | None,
    ) -> str | None:
        if display_name is None:
            return None

        normalized = str(
            display_name
        ).strip()

        if not normalized:
            return None

        if len(normalized) > cls.MAX_DISPLAY_NAME_LENGTH:
            raise ValueError(
                "display_name cannot exceed 200 characters."
            )

        return normalized

    @staticmethod
    def _generate_user_id() -> str:
        return str(uuid4())

    def create(
        self,
        *,
        user_id: str | None = None,
        display_name: str | None = None,
    ) -> User:
        normalized_user_id = (
            self._validate_user_id(user_id)
            if user_id is not None
            else self._generate_user_id()
        )

        normalized_display_name = (
            self._validate_display_name(
                display_name
            )
        )

        with Session(
            self.engine
        ) as session:
            existing = session.scalar(
                select(User).where(
                    User.id == normalized_user_id
                )
            )

            if existing is not None:
                raise ValueError(
                    f"User already exists: {normalized_user_id}"
                )

            user = User(
                id=normalized_user_id,
                display_name=normalized_display_name,
                is_active=True,
            )

            session.add(user)

            try:
                session.commit()
            except IntegrityError as exc:
                session.rollback()

                raise ValueError(
                    f"User already exists: {normalized_user_id}"
                ) from exc

            session.refresh(user)

            return user

    def get(
        self,
        *,
        user_id: str,
    ) -> User | None:
        normalized_user_id = self._validate_user_id(
            user_id
        )

        with Session(
            self.engine
        ) as session:
            return session.scalar(
                select(User).where(
                    User.id == normalized_user_id
                )
            )

    def get_or_create(
        self,
        *,
        user_id: str,
        display_name: str | None = None,
    ) -> User:
        normalized_user_id = self._validate_user_id(
            user_id
        )

        normalized_display_name = (
            self._validate_display_name(
                display_name
            )
        )

        with Session(
            self.engine
        ) as session:
            existing = session.scalar(
                select(User).where(
                    User.id == normalized_user_id
                )
            )

            if existing is not None:
                return existing

            user = User(
                id=normalized_user_id,
                display_name=normalized_display_name,
                is_active=True,
            )

            session.add(user)

            try:
                session.commit()
            except IntegrityError:
                session.rollback()

                existing = session.scalar(
                    select(User).where(
                        User.id == normalized_user_id
                    )
                )

                if existing is None:
                    raise

                return existing

            session.refresh(user)

            return user

    def update(
        self,
        *,
        user_id: str,
        display_name: str | None = None,
    ) -> User:
        normalized_user_id = self._validate_user_id(
            user_id
        )

        normalized_display_name = (
            self._validate_display_name(
                display_name
            )
        )

        with Session(
            self.engine
        ) as session:
            user = session.scalar(
                select(User).where(
                    User.id == normalized_user_id
                )
            )

            if user is None:
                raise ValueError(
                    f"User does not exist: {normalized_user_id}"
                )

            user.display_name = (
                normalized_display_name
            )

            user.updated_at = (
                self._utc_now_naive()
            )

            session.commit()
            session.refresh(user)

            return user

    def deactivate(
        self,
        *,
        user_id: str,
    ) -> User:
        return self._set_active_state(
            user_id=user_id,
            is_active=False,
        )

    def activate(
        self,
        *,
        user_id: str,
    ) -> User:
        return self._set_active_state(
            user_id=user_id,
            is_active=True,
        )

    def _set_active_state(
        self,
        *,
        user_id: str,
        is_active: bool,
    ) -> User:
        normalized_user_id = self._validate_user_id(
            user_id
        )

        with Session(
            self.engine
        ) as session:
            user = session.scalar(
                select(User).where(
                    User.id == normalized_user_id
                )
            )

            if user is None:
                raise ValueError(
                    f"User does not exist: {normalized_user_id}"
                )

            user.is_active = is_active
            user.updated_at = (
                self._utc_now_naive()
            )

            session.commit()
            session.refresh(user)

            return user
