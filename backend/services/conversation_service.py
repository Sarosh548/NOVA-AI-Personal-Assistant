from datetime import datetime

from sqlalchemy import select
from sqlalchemy.orm import Session

from database.connection import engine
from models.conversation import Conversation
from models.message import Message


class ConversationService:

    def create_conversation(
        self,
        user_id: str,
        title: str = "New Conversation",
    ) -> int:

        with Session(engine) as session:
            conversation = Conversation(
                user_id=user_id,
                title=title.strip() or "New Conversation",
            )

            session.add(conversation)
            session.commit()
            session.refresh(conversation)

            return conversation.id

    def get_or_create_conversation(
        self,
        user_id: str,
        conversation_id: int | None = None,
    ) -> int:

        with Session(engine) as session:

            if conversation_id is not None:
                conversation = session.scalar(
                    select(Conversation).where(
                        Conversation.id == conversation_id,
                        Conversation.user_id == user_id,
                    )
                )

                if conversation:
                    return conversation.id

            conversation = Conversation(
                user_id=user_id,
                title="New Conversation",
            )

            session.add(conversation)
            session.commit()
            session.refresh(conversation)

            return conversation.id

    def update_conversation_title(
        self,
        conversation_id: int,
        user_id: str,
        title: str,
    ) -> bool:

        cleaned_title = title.strip()

        if not cleaned_title:
            return False

        with Session(engine) as session:
            conversation = session.scalar(
                select(Conversation).where(
                    Conversation.id == conversation_id,
                    Conversation.user_id == user_id,
                )
            )

            if not conversation:
                return False

            conversation.title = cleaned_title[:200]
            conversation.updated_at = datetime.utcnow()

            session.commit()

            return True

    def save_message(
        self,
        user_id: str,
        conversation_id: int,
        role: str,
        content: str,
    ) -> None:

        if not content.strip():
            raise ValueError("content cannot be empty")

        valid_roles = {
            "user",
            "assistant",
            "system",
        }

        if role not in valid_roles:
            raise ValueError(
                "role must be user, assistant, or system"
            )

        with Session(engine) as session:

            conversation = session.scalar(
                select(Conversation).where(
                    Conversation.id == conversation_id,
                    Conversation.user_id == user_id,
                )
            )

            if not conversation:
                raise ValueError(
                    "Conversation does not exist or does not belong to user"
                )

            message = Message(
                user_id=user_id,
                conversation_id=conversation_id,
                role=role,
                content=content.strip(),
            )

            session.add(message)

            conversation.updated_at = datetime.utcnow()

            session.commit()

    def get_history(
        self,
        user_id: str,
        conversation_id: int,
        limit: int = 20,
    ) -> list[dict]:

        if limit < 1:
            raise ValueError(
                "limit must be greater than 0"
            )

        with Session(engine) as session:

            conversation = session.scalar(
                select(Conversation).where(
                    Conversation.id == conversation_id,
                    Conversation.user_id == user_id,
                )
            )

            if not conversation:
                return []

            statement = (
                select(Message)
                .where(
                    Message.user_id == user_id,
                    Message.conversation_id == conversation_id,
                )
                .order_by(Message.created_at.desc())
                .limit(limit)
            )

            messages = session.scalars(statement).all()
            messages.reverse()

            return [
                {
                    "role": message.role,
                    "content": message.content,
                }
                for message in messages
            ]

    def get_conversation_state(
        self,
        user_id: str,
        conversation_id: int,
    ) -> dict:
        """
        Derive the current conversational state from the latest message.

        This is intentionally derived rather than stored in the database
        for now. Later, real-time voice state can be persisted separately.
        """

        with Session(engine) as session:

            conversation = session.scalar(
                select(Conversation).where(
                    Conversation.id == conversation_id,
                    Conversation.user_id == user_id,
                )
            )

            if not conversation:
                return {
                    "state": "unknown",
                    "last_role": None,
                    "should_listen": False,
                }

            latest_message = session.scalar(
                select(Message)
                .where(
                    Message.user_id == user_id,
                    Message.conversation_id == conversation_id,
                )
                .order_by(Message.created_at.desc())
            )

            if not latest_message:
                return {
                    "state": "new",
                    "last_role": None,
                    "should_listen": True,
                }

            if latest_message.role == "assistant":
                return {
                    "state": "awaiting_user",
                    "last_role": "assistant",
                    "should_listen": True,
                }

            if latest_message.role == "user":
                return {
                    "state": "processing",
                    "last_role": "user",
                    "should_listen": False,
                }

            return {
                "state": "awaiting_user",
                "last_role": latest_message.role,
                "should_listen": True,
            }

    def get_conversations(
        self,
        user_id: str,
        limit: int = 50,
    ) -> list[dict]:

        if limit < 1:
            raise ValueError(
                "limit must be greater than 0"
            )

        with Session(engine) as session:

            statement = (
                select(Conversation)
                .where(
                    Conversation.user_id == user_id
                )
                .order_by(
                    Conversation.updated_at.desc()
                )
                .limit(limit)
            )

            conversations = session.scalars(
                statement
            ).all()

            return [
                {
                    "id": conversation.id,
                    "title": conversation.title,
                    "created_at": conversation.created_at,
                    "updated_at": conversation.updated_at,
                }
                for conversation in conversations
            ]

    def delete_conversation(
        self,
        user_id: str,
        conversation_id: int,
    ) -> bool:

        with Session(engine) as session:

            conversation = session.scalar(
                select(Conversation).where(
                    Conversation.id == conversation_id,
                    Conversation.user_id == user_id,
                )
            )

            if not conversation:
                return False

            session.delete(conversation)
            session.commit()

            return True