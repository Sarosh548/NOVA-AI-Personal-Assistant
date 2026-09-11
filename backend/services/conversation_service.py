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
                title=title,
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

    def save_message(
        self,
        user_id: str,
        conversation_id: int,
        role: str,
        content: str,
    ) -> None:

        with Session(engine) as session:

            message = Message(
                user_id=user_id,
                conversation_id=conversation_id,
                role=role,
                content=content,
            )

            session.add(message)
            session.commit()

    def get_history(
        self,
        user_id: str,
        conversation_id: int,
        limit: int = 20,
    ) -> list[dict]:

        with Session(engine) as session:

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