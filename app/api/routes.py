from fastapi import APIRouter

from app.api.schemas import ChatRequest, ChatResponse, ResetSessionRequest
from app.core.config import LLM_MODEL, LLM_PROVIDER, logger
from app.services.chat_service import process_message, reset_session

router = APIRouter()


@router.post("/chat", response_model=ChatResponse)
async def chat(req: ChatRequest):
    """Receive {"phone","message"} and return {"reply": "...", "images": [...]}."""
    logger.info("Message from %s: %s", req.phone, req.message)
    try:
        reply, images = process_message(req.phone, req.message)
    except Exception:
        logger.exception("Unhandled error while processing message from %s", req.phone)
        reply, images = ("معذرة، حصل خطأ بسيط. ممكن تعيد طلبك؟", [])
    return {"reply": reply, "images": images}


@router.post("/session/reset")
async def session_reset(req: ResetSessionRequest):
    """Clear in-memory conversation state and search slots for a phone number."""
    reset_session(req.phone)
    return {"status": "ok", "phone": req.phone}


@router.get("/health")
@router.get("/")
async def health():
    return {
        "status": "ok",
        "service": "realestate-chat-api",
        "provider": LLM_PROVIDER,
        "model": LLM_MODEL,
    }
