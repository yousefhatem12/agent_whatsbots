from __future__ import annotations

from typing import Optional

from pydantic import BaseModel, ConfigDict, Field, field_validator


class ChatRequest(BaseModel):
    model_config = ConfigDict(extra="ignore")

    phone: str = Field(default="unknown", min_length=1, description="Customer phone number / session identifier")
    message: str = Field(..., min_length=1, description="Incoming customer message text")
    name: Optional[str] = Field(default=None, description="Optional customer name from WhatsApp webhook")

    @field_validator("phone", "message")
    @classmethod
    def _strip_non_empty(cls, value: str) -> str:
        cleaned = str(value).strip()
        if not cleaned:
            raise ValueError("Field must not be empty or whitespace only.")
        return cleaned


class ChatResponse(BaseModel):
    status: str = "success"
    reply: str
    res: str = ""
    images: list[str] = Field(default_factory=list)


class ResetSessionRequest(BaseModel):
    phone: str = Field(..., min_length=1, description="Customer phone number to reset")
