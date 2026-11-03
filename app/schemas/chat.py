from pydantic import BaseModel, ConfigDict, Field


class WebhookRequest(BaseModel):
    """Incoming WhatsApp flow webhook payload (e.g. from MashiiBOT)."""

    model_config = ConfigDict(extra="ignore")

    phone: str = Field(
        default="unknown",
        examples=["201000000000"],
        description="Sender WhatsApp phone number (e.g. {{{senderMobile}}})",
    )
    message: str = Field(
        default="",
        examples=["What products are available in stock?"],
        description="User message or query text (e.g. {{{senderMessage}}})",
    )
    name: str | None = Field(
        default=None,
        examples=["Ahmed"],
        description="Optional sender name (e.g. {{{senderName}}})",
    )


class WebhookResponse(BaseModel):
    """Structured response payload returned to the WhatsApp flow orchestrator."""

    status: str = Field(
        default="success",
        examples=["success"],
        description="Execution status ('success' or 'error') for Condition Router nodes",
    )
    reply: str = Field(
        ...,
        examples=["Here are the items found in the database..."],
        description="Generated response text mapped to {{{reply}}} in WhatsApp flow",
    )
    res: str = Field(
        default="",
        examples=["Here are the items found in the database..."],
        description="Alias for reply mapped to {{{res}}} in WhatsApp flow",
    )

