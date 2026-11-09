from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app.api.routes import router
from app.core.config import DB_HOST, DB_NAME, DB_USER, LLM_MODEL, LLM_PROVIDER, logger


@asynccontextmanager
async def lifespan(_app: FastAPI):
    logger.info(
        "Startup complete. Provider=%s Model=%s DB=%s@%s/%s",
        LLM_PROVIDER,
        LLM_MODEL,
        DB_USER,
        DB_HOST,
        DB_NAME,
    )
    yield


app = FastAPI(
    title="Riyadh Real Estate Chat API",
    description="WhatsApp customer service bot API for Mashi Real Estate Marketing in Riyadh.",
    version="1.1.0",
    lifespan=lifespan,
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(router)
