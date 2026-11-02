# WhatsApp AI SQL Agent (`agent.md`)

## Overview
The **FastAPI MySQL WhatsApp Agent** is an asynchronous AI-powered backend service that connects WhatsApp flow orchestrators (such as **MashiiBOT**) with a **MySQL database** (local or cPanel-hosted) and an **OpenAI-compatible LLM** (Groq, OpenAI, Google Gemini, or Ollama) using **LangChain's SQL Agent**.

---

## Agent Architecture & Execution Flow

1. **Incoming Webhook (`POST /`, `POST /webhook`, `POST /endpoint`)**
   - Receives the JSON payload from the WhatsApp flow **Make Request** node:
     ```json
     {
       "phone": "{{{senderMobile}}}",
       "message": "{{{senderMessage}}}"
     }
     ```
   - Validated by [`WebhookRequest`](app/schemas/chat.py).

2. **User Identification & Conversation Memory (`app/crud/crud_chat.py`)**
   - Looks up or creates a `User` record by WhatsApp phone number (`get_or_create_user`).
   - Fetches the last 5 conversation turns from the `chat_history` table (`get_recent_chat_history`) to provide multi-turn conversational context.

3. **Dynamic SQL Agent & LLM Reasoning (`app/services/agent.py`)**
   - Uses `ChatOpenAI` configured via `.env` (`OPENAI_API_KEY`, `OPENAI_BASE_URL`, `OPENAI_MODEL`).
   - Connects LangChain's `SQLDatabase` toolkit to the SQLAlchemy MySQL engine (`create_sql_agent`).
   - Enforces a strict system prompt (`SYSTEM_PREFIX`):
     - Formats answers concisely for WhatsApp (bullet points, no markdown tables).
     - Replies in the same language as the user (supports Arabic & English automatically).
     - Prohibits destructive SQL operations (`INSERT`, `UPDATE`, `DELETE`, `DROP`, `ALTER`, `TRUNCATE`).

4. **Graceful Multi-Layer Fallbacks**
   - **Database Unreachable Fallback**: If the remote cPanel MySQL connection is temporarily unavailable or IP-restricted, the agent automatically falls back to direct LLM response generation so the WhatsApp webhook still returns `200 OK`.
   - **No API Key Fallback**: If `OPENAI_API_KEY` is not set, `_fallback_product_lookup` queries available products directly via SQLAlchemy CRUD (`get_available_products`).

5. **Audit & History Persistence**
   - Saves every user message and generated reply into the `chat_history` table (`save_chat_message`).
   - Returns a structured [`WebhookResponse`](app/schemas/chat.py):
     ```json
     {
       "reply": "Generated response text..."
     }
     ```

---

## Key Agent Files

| File | Responsibility |
| :--- | :--- |
| `app/main.py` | FastAPI application, CORS middleware, `POST /`, `POST /webhook`, `POST /endpoint`, `POST /test-db`, and `GET /health` routes |
| `app/services/agent.py` | Core AI agent logic (`process_whatsapp_message`), LangChain SQL Agent setup, and fallback handlers |
| `app/crud/crud_chat.py` | Database CRUD operations for users, chat history, and product inventory |
| `app/models/user.py` | SQLAlchemy ORM models (`User`, `Product`, `ChatHistory`) |
| `app/database/session.py` | SQLAlchemy engine & connection pooling tuned for cPanel MySQL (`pool_pre_ping`, `pool_recycle=280`) |
| `app/config.py` | Pydantic settings with URL-encoding for special characters in cPanel passwords |

---

## Endpoints Summary

- **`POST /` | `POST /webhook` | `POST /endpoint`**
  - Main webhook endpoint for WhatsApp flow orchestrators (MashiiBOT).
- **`POST /test-db`**
  - Diagnostic endpoint that tests the cPanel MySQL connection and returns the MySQL version and table list.
- **`GET /health`**
  - Lightweight health check endpoint returning `{"status": "ok"}`.
