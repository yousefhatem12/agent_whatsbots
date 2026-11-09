# Riyadh Real Estate WhatsApp Chat API (`agent_whatsbots`)

FastAPI-powered conversational AI backend for **Mashi Real Estate Marketing (ماشي للتسويق العقاري)**, helping customers find furnished apartments for monthly and annual rent in Riyadh via WhatsApp.

---

## Key Features

- **Intent-First Conversational Search**: Extracts customer preferences (neighborhood, direction, apartment type, budget, sort order, exclusions) in any order across turns.
- **Live Inventory Validation**: Dynamically queries and caches active neighborhoods, apartment types (`studio`, `one_bedroom`, `two_bedroom`), and real price ranges directly from MySQL (`CACHE_TTL = 60s`).
- **Smart Fallback Hierarchy**:
  1. Exact apartment type & neighborhood within budget
  2. Above-budget stock in the same neighborhood & type
  3. Alternative apartment types in the same neighborhood
  4. Soon-to-be-available units (`search_upcoming_properties`)
  5. Same-direction neighborhoods in Riyadh (`شمال`, `شرق`, `غرب`, `وسط`, `جنوب`)
- **Dual LLM Provider Support**: Works seamlessly with **DeepSeek** (`deepseek-v4-flash`, with configurable thinking mode) and **OpenAI** (`gpt-4o`) via the OpenAI-compatible SDK.
- **WhatsApp-Native Formatting Guardrails**: Enforces single-asterisk bold (`*نص*`), strips emojis, formats phone numbers into international `+966` format without invisible bidi characters, and guarantees canonical property links.

---

## Project Structure

```text
.
├── app/
│   ├── api/
│   │   ├── routes.py            # FastAPI endpoints (/chat, /session/reset, /health, /)
│   │   └── schemas.py           # Pydantic request/response models & validation
│   ├── core/
│   │   └── config.py            # Environment & LLM/Database configuration
│   ├── db/
│   │   ├── database.py          # SQLAlchemy read-only MySQL engine & property queries
│   │   └── seed_data.py         # Live inventory cache (neighborhoods, types, price ranges)
│   ├── services/
│   │   ├── apartment_types.py   # Arabic apartment type classification & neighborhood helpers
│   │   ├── chat_service.py      # Session state, slot extraction, tool execution & LLM loop
│   │   └── prompts.py           # System prompt, guardrails, policies & tool schemas
│   └── main.py                  # FastAPI application entrypoint & lifespan handler
├── main.py                      # Local Uvicorn runner
├── passenger_wsgi.py            # cPanel / Passenger WSGI adapter (via a2wsgi)
├── start_uvicorn.sh             # Production cron/daemon startup script
├── requirements.txt             # Python dependencies
└── .env.example                 # Example environment variables template
```

---

## Quick Start

### 1. Install Dependencies

```bash
python -m venv .venv
# Windows
.venv\Scripts\activate
# Linux / macOS
source .venv/bin/activate

pip install -r requirements.txt
```

### 2. Configure Environment

Copy `.env.example` to `.env` and fill in your credentials:

```bash
cp .env.example .env
```

Required settings in `.env`:
- `LLM_PROVIDER`: `deepseek` or `openai`
- `DEEPSEEK_API_KEY` or `OPENAI_API_KEY` (or generic `LLM_API_KEY`)
- `DB_HOST`, `DB_PORT`, `DB_USER`, `DB_PASSWORD`, `DB_NAME`

### 3. Run the Server

```bash
python main.py
# Or directly with Uvicorn:
uvicorn app.main:app --host 0.0.0.0 --port 8000 --reload
```

---

## API Endpoints

### `POST /chat`
Process a customer WhatsApp message and return the assistant's reply.

**Request Body:**
```json
{
  "phone": "+966500000000",
  "message": "السلام عليكم، أبغى غرفة وصالة في النرجس"
}
```

**Response Body:**
```json
{
  "reply": "الأسعار لشقق غرفة وصالة في النرجس تبدأ من ...",
  "images": []
}
```

### `POST /session/reset`
Clear the in-memory conversation history, search results, and extracted criteria for a specific phone number.

**Request Body:**
```json
{
  "phone": "+966500000000"
}
```

### `GET /health` & `GET /`
Health check returning service status and active LLM provider/model.

