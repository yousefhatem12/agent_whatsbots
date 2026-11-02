from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models.user import ChatHistory, Product, User


def get_or_create_user(db: Session, phone: str) -> User:
    """Retrieve an existing user by phone number or create a new record."""
    stmt = select(User).where(User.phone == phone)
    user = db.scalars(stmt).first()
    if not user:
        user = User(phone=phone)
        db.add(user)
        db.commit()
        db.refresh(user)
    return user


def get_recent_chat_history(db: Session, user_id: int, limit: int = 5) -> list[ChatHistory]:
    """Fetch the most recent conversation turns for a given user in chronological order."""
    stmt = (
        select(ChatHistory)
        .where(ChatHistory.user_id == user_id)
        .order_by(ChatHistory.created_at.desc())
        .limit(limit)
    )
    records = list(db.scalars(stmt).all())
    records.reverse()
    return records


def save_chat_message(
    db: Session,
    user_id: int,
    user_message: str,
    bot_reply: str,
) -> ChatHistory:
    """Persist a user message and its generated agent reply to the database."""
    entry = ChatHistory(
        user_id=user_id,
        user_message=user_message,
        bot_reply=bot_reply,
    )
    db.add(entry)
    db.commit()
    db.refresh(entry)
    return entry


def get_available_products(db: Session, limit: int = 20) -> list[Product]:
    """Return products currently in stock (stock_quantity > 0)."""
    stmt = (
        select(Product)
        .where(Product.stock_quantity > 0)
        .order_by(Product.name.asc())
        .limit(limit)
    )
    return list(db.scalars(stmt).all())

