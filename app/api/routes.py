import json
import re

from fastapi import APIRouter, Request
from sqlalchemy import inspect, text

from app.api.schemas import ChatResponse, ResetSessionRequest
from app.core.config import DB_HOST, DB_NAME, LLM_MODEL, LLM_PROVIDER, logger
from app.db.database import engine
from app.services.chat_service import process_message, reset_session

router = APIRouter()


def _parse_incoming_payload(raw_bytes: bytes) -> tuple[str, str]:
    """Tolerantly extract (phone, message) even when webhook templates inject unescaped quotes/newlines."""
    raw_text = (raw_bytes or b"").decode("utf-8", errors="replace").strip()
    if not raw_text:
        return "unknown", "مرحبا"

    try:
        data = json.loads(raw_text, strict=False)
        if isinstance(data, dict):
            phone = str(data.get("phone") or data.get("senderMobile") or "unknown").strip() or "unknown"
            message = str(data.get("message") or data.get("senderMessage") or "").strip() or "مرحبا"
            return phone, message
    except Exception:
        pass

    phone_match = re.search(r'"phone"\s*:\s*"([^"]*)"', raw_text)
    phone = phone_match.group(1).strip() if phone_match else "unknown"

    msg_match = re.search(r'"message"\s*:\s*"([\s\S]*)"\s*\}', raw_text)
    if msg_match:
        message = msg_match.group(1).strip().strip('"').strip()
    else:
        message = raw_text
    return phone or "unknown", message or "مرحبا"


@router.post("/chat", response_model=ChatResponse)
@router.post("/webhook", response_model=ChatResponse)
@router.post("/endpoint", response_model=ChatResponse)
@router.post("/", response_model=ChatResponse)
async def chat(request: Request):
    """Receive {"phone","message"} and return {"status": "success", "reply": "...", "res": "...", "images": [...]}."""
    raw_bytes = await request.body()
    phone, message = _parse_incoming_payload(raw_bytes)
    logger.info("Message from %s: %s", phone, message)
    try:
        reply, images = process_message(phone, message)
        status_val = "success"
    except Exception:
        logger.exception("Unhandled error while processing message from %s", phone)
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
