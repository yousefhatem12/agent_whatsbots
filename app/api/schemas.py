from pydantic import BaseModel, Field, field_validator


class ChatRequest(BaseModel):
    phone: str = Field(..., min_length=1, description="Customer phone number / session identifier")
    message: str = Field(..., min_length=1, description="Incoming customer message text")

    @field_validator("phone", "message")
    @classmethod
    def _strip_non_empty(cls, value: str) -> str:
        cleaned = value.strip()
        if not cleaned:
            raise ValueError("Field must not be empty or whitespace only.")
        return cleaned


class ChatResponse(BaseModel):
    reply: str
    images: list[str] = Field(default_factory=list)


class ResetSessionRequest(BaseModel):
    phone: str = Field(..., min_length=1, description="Customer phone number to reset")
