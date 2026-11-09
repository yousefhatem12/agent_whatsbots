from fastapi import APIRouter
from sqlalchemy import inspect, text

from app.api.schemas import ChatRequest, ChatResponse, ResetSessionRequest
from app.core.config import DB_HOST, DB_NAME, LLM_MODEL, LLM_PROVIDER, logger
from app.db.database import engine
from app.services.chat_service import process_message, reset_session

router = APIRouter()


@router.post("/chat", response_model=ChatResponse)
@router.post("/webhook", response_model=ChatResponse)
@router.post("/endpoint", response_model=ChatResponse)
@router.post("/", response_model=ChatResponse)
async def chat(req: ChatRequest):
    """Receive {"phone","message"} and return {"status": "success", "reply": "...", "res": "...", "images": [...]}."""
    logger.info("Message from %s: %s", req.phone, req.message)
    try:
        reply, images = process_message(req.phone, req.message)
        status_val = "success"
    except Exception:
        logger.exception("Unhandled error while processing message from %s", req.phone)
        reply, images = ("معذرة، حصل خطأ بسيط. ممكن تعيد طلبك؟", [])
        status_val = "error"
    return {"status": status_val, "reply": reply, "res": reply, "images": images}


@router.post("/session/reset")
async def session_reset(req: ResetSessionRequest):
    """Clear in-memory conversation state and search slots for a phone number."""
    reset_session(req.phone)
    return {"status": "ok", "phone": req.phone}


@router.get("/test-db")
@router.post("/test-db")
async def test_db_connection():
    """Verify MySQL database connection and inspect tables."""
    try:
        with engine.connect() as conn:
            version = conn.execute(text("SELECT VERSION()")).scalar()
            current_db = conn.execute(text("SELECT DATABASE()")).scalar()
        tables = inspect(engine).get_table_names()
        return {
            "connected": True,
            "host": DB_HOST,
            "database": current_db,
            "mysql_version": version,
            "tables_count": len(tables),
            "tables": tables,
        }
    except Exception as exc:
        return {
            "connected": False,
            "host": DB_HOST,
            "database": DB_NAME,
            "error": str(exc),
        }


@router.get("/health")
@router.get("/")
async def health():
    return {
        "status": "ok",
        "service": "realestate-chat-api",
        "provider": LLM_PROVIDER,
        "model": LLM_MODEL,
    }
