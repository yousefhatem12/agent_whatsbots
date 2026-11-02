import logging
import sys
from contextlib import asynccontextmanager
from fastapi import Depends, FastAPI, status
from fastapi.middleware.cors import CORSMiddleware
from sqlalchemy import inspect, text
from sqlalchemy.orm import Session

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
if hasattr(sys.stderr, "reconfigure"):
    sys.stderr.reconfigure(encoding="utf-8", errors="replace")

from app.config import settings
from app.database.base import Base
from app.database.session import engine, get_db
from app.models import user as _models  # noqa: F401 - register ORM models with Base.metadata
from app.schemas.chat import WebhookRequest, WebhookResponse
from app.services.agent import process_whatsapp_message

logging.basicConfig(
    level=logging.DEBUG if settings.DEBUG else logging.INFO,
    format="%(asctime)s | %(levelname)-8s | %(name)s | %(message)s",
)
logger = logging.getLogger(__name__)


@asynccontextmanager
async def lifespan(app: FastAPI):
    """Initialize database tables on startup if the MySQL server is reachable."""
    try:
        Base.metadata.create_all(bind=engine)
        logger.info("Database tables verified/created successfully.")
    except Exception as exc:
        logger.warning(
            "Database initialization skipped (check DATABASE_URL in .env): %s",
            exc,
        )
    yield


app = FastAPI(
    title=settings.APP_NAME,
    description=(
        "Asynchronous FastAPI service designed to receive Webhook requests from "
        "WhatsApp flow orchestrators (such as MashiiBOT), process user queries "
        "using MySQL database contexts, and return structured response payloads."
    ),
    version="1.0.0",
    lifespan=lifespan,
)


app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


@app.post(
    "/",
    response_model=WebhookResponse,
    status_code=status.HTTP_200_OK,
    summary="WhatsApp Flow Webhook Endpoint (Root)",
    description="Receives a user's phone number and message from a WhatsApp orchestrator and returns an AI/DB-backed reply.",
)
@app.post(
    "/webhook",
    response_model=WebhookResponse,
    status_code=status.HTTP_200_OK,
    summary="WhatsApp Flow Webhook Endpoint (/webhook)",
)
@app.post(
    "/endpoint",
    response_model=WebhookResponse,
    status_code=status.HTTP_200_OK,
    summary="WhatsApp Flow Webhook Endpoint (/endpoint)",
)
async def whatsapp_webhook(
    payload: WebhookRequest,
    db: Session = Depends(get_db),
) -> WebhookResponse:
    """Handle incoming WhatsApp webhook requests."""
    reply_text = await process_whatsapp_message(
        db=db,
        phone=payload.phone,
        message=payload.message,
    )
    status_val = "success" if reply_text else "error"
    return WebhookResponse(status=status_val, reply=reply_text)


@app.post(
    "/test-db",
    status_code=status.HTTP_200_OK,
    summary="Test cPanel MySQL Database Connection",
    description="Tests the connection to the configured cPanel MySQL database and returns the server version and table names.",
)
async def test_db_connection(db: Session = Depends(get_db)) -> dict:
    """Test the cPanel MySQL database connection via POST."""
    try:
        version = db.execute(text("SELECT VERSION()")).scalar()
        current_db = db.execute(text("SELECT DATABASE()")).scalar()
        tables = inspect(engine).get_table_names()
        return {
            "connected": True,
            "host": settings.DB_HOST or "from DATABASE_URL",
            "database": current_db,
            "mysql_version": version,
            "tables_count": len(tables),
            "tables": tables,
        }
    except Exception as exc:
        return {
            "connected": False,
            "host": settings.DB_HOST or "from DATABASE_URL",
            "database": settings.DB_NAME,
            "error": str(exc),
            "fix": (
                "Open cPanel -> Remote Database Access (Remote MySQL) -> "
                "Add Host '197.35.17.1' or '%' -> Click Add Host."
            ),
        }


@app.get(
    "/health",
    status_code=status.HTTP_200_OK,
    summary="Health Check",
)
async def health_check() -> dict[str, str]:
    """Simple health check endpoint."""
    return {"status": "ok", "service": settings.APP_NAME}

