import logging
from sqlalchemy.orm import Session

from langchain_community.agent_toolkits import create_sql_agent
from langchain_community.utilities import SQLDatabase
from langchain_openai import ChatOpenAI

from app.config import settings
from app.crud.crud_chat import (
    get_available_products,
    get_or_create_user,
    get_recent_chat_history,
    save_chat_message,
)
from app.database.session import engine

logger = logging.getLogger(__name__)

SYSTEM_PREFIX = """You are a helpful WhatsApp customer support and database assistant.
You have access to a MySQL database. Answer the user's question accurately and concisely
based on the data in the database.
- Format your reply clearly for WhatsApp (short bullet points, friendly tone, no markdown tables).
- Never execute destructive SQL statements (INSERT, UPDATE, DELETE, DROP, ALTER, TRUNCATE).
- If the user asks in Arabic, reply in Arabic; otherwise reply in the language of the user's message.
"""


def _build_conversation_context(db: Session, phone: str) -> tuple[int | None, str]:
    """Retrieve or register the user and format recent conversation turns."""
    try:
        user = get_or_create_user(db, phone=phone)
        history = get_recent_chat_history(db, user_id=user.id, limit=5)
        if not history:
            return user.id, "No prior conversation history."

        formatted_turns = []
        for turn in history:
            formatted_turns.append(f"User: {turn.user_message}\nAssistant: {turn.bot_reply}")
        return user.id, "\n".join(formatted_turns)
    except Exception as exc:
        logger.warning("Could not load conversation history for %s: %s", phone, exc)
        db.rollback()
        return None, "Conversation history unavailable."


def _fallback_product_lookup(db: Session) -> str:
    """Fallback database lookup if OPENAI_API_KEY is not configured."""
    try:
        products = get_available_products(db)
        if not products:
            return "No products are currently available in stock."
        lines = ["Here are the items found in the database:"]
        for item in products:
            lines.append(f"- {item.name}: ${item.price:.2f} ({item.stock_quantity} in stock)")
        return "\n".join(lines)
    except Exception as exc:
        logger.error("Fallback DB query failed: %s", exc)
        return "Service is running, but the database or OpenAI API key is not configured yet."


# Cached SQLDatabase instance so large cPanel databases (e.g. shgarde_dummy) are not re-reflected on every request
_cached_sql_db: SQLDatabase | None = None


def _get_sql_database() -> SQLDatabase:
    """Return a cached SQLDatabase instance with lightweight table reflection."""
    global _cached_sql_db
    if _cached_sql_db is None:
        _cached_sql_db = SQLDatabase(
            engine,
            sample_rows_in_table_info=1,
            max_string_length=150,
        )
    return _cached_sql_db


async def process_whatsapp_message(db: Session, phone: str, message: str) -> str:
    """Process an incoming WhatsApp message using the LangChain SQL Agent and MySQL context."""
    if not message or not message.strip():
        return "مرحباً بك! كيف يمكنني مساعدتك اليوم؟"

    user_id, history_context = _build_conversation_context(db, phone=phone)

    if not settings.OPENAI_API_KEY or settings.OPENAI_API_KEY == "your_openai_api_key_here":
        logger.warning("OPENAI_API_KEY is not set; using direct CRUD fallback.")
        reply = _fallback_product_lookup(db)
    else:
        try:
            llm = ChatOpenAI(
                model=settings.OPENAI_MODEL,
                temperature=0,
                api_key=settings.OPENAI_API_KEY,
                base_url=settings.OPENAI_BASE_URL or None,
                timeout=12,
                max_retries=1,
            )
            try:
                sql_db = _get_sql_database()
                agent_executor = create_sql_agent(
                    llm=llm,
                    db=sql_db,
                    agent_type="openai-tools",
                    prefix=SYSTEM_PREFIX,
                    verbose=settings.DEBUG,
                    max_iterations=4,
                    max_execution_time=12,
                )

                prompt = (
                    f"Customer WhatsApp Phone: {phone}\n"
                    f"Recent Conversation History:\n{history_context}\n\n"
                    f"Current User Question: {message}"
                )
                result = await agent_executor.ainvoke({"input": prompt})
                reply = result.get("output", "").strip() or "لم أتمكن من العثور على إجابة، هل يمكنك توضيح سؤالك؟"
            except Exception as db_exc:
                logger.warning(
                    "SQL Agent DB connection unavailable (%s); falling back to direct LLM response.",
                    db_exc,
                )
                ai_msg = await llm.ainvoke(
                    [
                        ("system", SYSTEM_PREFIX),
                        ("human", f"Customer Phone: {phone}\nQuestion: {message}"),
                    ]
                )
                reply = str(ai_msg.content).strip()
        except Exception as exc:
            logger.exception("Error while processing message for phone %s: %s", phone, exc)
            reply = ""

    if user_id is not None:
        try:
            save_chat_message(
                db=db,
                user_id=user_id,
                user_message=message,
                bot_reply=reply,
            )
        except Exception as exc:
            logger.warning("Failed to save chat history for user_id=%s: %s", user_id, exc)
            db.rollback()

    return reply

