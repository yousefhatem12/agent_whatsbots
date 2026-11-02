# FastAPI MySQL WhatsApp Agent

An asynchronous FastAPI service designed to receive Webhook requests from WhatsApp flow orchestrators (such as MashiiBOT), process user queries using MySQL database contexts, and return structured response payloads.

---

## 🏗 Project Architecture

```text
fastapi-mysql-agent/
│
├── app/
│   ├── __init__.py
│   ├── main.py              # FastAPI app initialization & webhook routes
│   ├── config.py            # Environment & app configuration settings
│   │
│   ├── database/
│   │   ├── __init__.py
│   │   ├── session.py       # SQLAlchemy engine & DB session dependency
│   │   └── base.py          # Declarative Base for ORM models
│   │
│   ├── models/
│   │   ├── __init__.py
│   │   └── user.py          # SQLAlchemy ORM database models (User, Product, ChatHistory)
│   │
│   ├── schemas/
│   │   ├── __init__.py
│   │   └── chat.py          # Pydantic models for request/response validation
│   │
│   ├── crud/
│   │   ├── __init__.py
│   │   └── crud_chat.py     # Database query & data handling operations
│   │
│   └── services/
│       ├── __init__.py
│       └── agent.py         # AI agent logic / DB processing engine
│
├── .env.example             # Template for environment variables
├── .env                     # Local environment file (git-ignored)
├── .gitignore               # Git ignore rules
├── requirements.txt         # Project dependencies
└── README.md                # Project documentation
```

---

## 🚀 Getting Started

### 1. Prerequisites
- **Python**: Version 3.10 or higher
- **MySQL Server**: Running locally or on a remote instance

### 2. Environment Setup
Clone or open the project directory in your workspace, then create and activate a virtual environment:

```bash
# Create virtual environment
python -m venv venv

# Activate on Linux/macOS
source venv/bin/activate

# Activate on Windows (PowerShell)
.\venv\Scripts\Activate.ps1
```

Install the required dependencies:

```bash
pip install -r requirements.txt
```

### 3. Environment Variables Configuration
Copy `.env.example` to `.env` and configure your database credentials and API keys:

```bash
cp .env.example .env
```

Set the variables inside `.env`:

```env
DATABASE_URL=mysql+pymysql://<DB_USER>:<DB_PASSWORD>@<DB_HOST>:<DB_PORT>/<DB_NAME>
OPENAI_API_KEY=your_openai_api_key_here
OPENAI_MODEL=gpt-4o-mini
```

---

## 🏃 Running the Application

Start the FastAPI development server with live reload:

```bash
uvicorn app.main:app --host 0.0.0.0 --port 8000 --reload
```

The interactive API documentation (Swagger UI) will be accessible at:
- **Swagger Docs**: http://localhost:8000/docs
- **ReDoc**: http://localhost:8000/redoc

---

## 📡 Webhook Integration Specifications

- **Endpoint**: `POST /`
- Designed for direct integration with WhatsApp flow modules (e.g., MashiiBOT Make Request nodes).

### Expected Request Payload
```json
{
  "phone": "201000000000",
  "message": "What products are available in stock?"
}
```

### Expected Response Payload
```json
{
  "reply": "Here are the items found in the database..."
}
```

---

## 🛠 Technology Stack
- **Framework**: [FastAPI](https://fastapi.tiangolo.com/)
- **Database Connector**: [SQLAlchemy](https://www.sqlalchemy.org/) + [PyMySQL](https://pymysql.readthedocs.io/)
- **Data Validation**: [Pydantic v2](https://docs.pydantic.dev/)
- **Server**: [Uvicorn](https://www.uvicorn.org/)
- **LLM / Agent Layer**: OpenAI / LangChain (configurable in `app/services/agent.py`)

