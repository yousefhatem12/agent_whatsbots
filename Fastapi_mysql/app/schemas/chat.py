from pydantic import BaseModel, Field


class WebhookRequest(BaseModel):
    """Incoming WhatsApp flow webhook payload (e.g. from MashiiBOT)."""

    phone: str = Field(
        ...,
        min_length=1,
        max_length=100,
        examples=["201000000000"],
        description="Sender WhatsApp phone number (or template variable {{{senderMobile}}})",
    )
    message: str = Field(
        ...,
        min_length=1,
        examples=["What products are available in stock?"],
        description="User message or query text (or template variable {{{senderMessage}}})",
    )


class WebhookResponse(BaseModel):
    """Structured response payload returned to the WhatsApp flow orchestrator."""

    reply: str = Field(
        ...,
        examples=["Here are the items found in the database..."],
        description="Generated response text to send back to the WhatsApp user",
    )

