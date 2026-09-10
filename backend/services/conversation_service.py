from sqlalchemy import select
from sqlalchemy.orm import Session

from database.connection import engine
from models.message import Message


class ConversationService:
    def save_message(
        self,
        user_id: str,
        role: str,
        content: str,
    ) -> None:
        with Session(engine) as session:
            message = Message(
                user_id=user_id,
                role=role,
                content=content,
            )

            session.add(message)
            session.commit()

    def get_history(
        self,
        user_id: str,
        limit: int = 20,
    ) -> list[dict]:
        with Session(engine) as session:
            statement = (
                select(Message)
                .where(Message.user_id == user_id)
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