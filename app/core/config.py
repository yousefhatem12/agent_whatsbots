import os
import logging
from urllib.parse import quote_plus

from dotenv import load_dotenv

load_dotenv(override=True)

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")
logger = logging.getLogger("realestate-chat")


def _env(name: str, default: str | None = None) -> str | None:
    """Read a non-empty environment variable, falling back when it is empty."""
    value = os.getenv(name)
    if value is None:
        return default
    value = value.strip()
    return value or default


# Provider-specific settings are kept for backwards compatibility with the
# existing .env file. The generic LLM_* settings below are the preferred API.
OPENAI_API_KEY = _env("OPENAI_API_KEY")
OPENAI_MODEL = _env("OPENAI_MODEL", "gpt-4o")
OPENAI_BASE_URL = _env("OPENAI_BASE_URL")

DEEPSEEK_API_KEY = _env("DEEPSEEK_API_KEY")
DEEPSEEK_MODEL = _env("DEEPSEEK_MODEL", "deepseek-v4-flash")
DEEPSEEK_BASE_URL = _env("DEEPSEEK_BASE_URL", "https://api.deepseek.com")

LLM_PROVIDER = (_env("LLM_PROVIDER", "openai") or "openai").lower()
if LLM_PROVIDER not in {"openai", "deepseek"}:
    raise ValueError(
        "Unsupported LLM_PROVIDER={!r}. Use 'openai' or 'deepseek'.".format(LLM_PROVIDER)
    )

if LLM_PROVIDER == "deepseek":
    _provider_model = DEEPSEEK_MODEL
    _provider_api_key = DEEPSEEK_API_KEY
    _provider_base_url = DEEPSEEK_BASE_URL
else:
    _provider_model = OPENAI_MODEL
    _provider_api_key = OPENAI_API_KEY
    _provider_base_url = OPENAI_BASE_URL

LLM_MODEL = _env("LLM_MODEL", _provider_model)
LLM_API_KEY = _env("LLM_API_KEY", _provider_api_key)
LLM_BASE_URL = _env("LLM_BASE_URL", _provider_base_url)
if not LLM_API_KEY:
    raise RuntimeError(
        "Missing API key for {!r}. Set LLM_API_KEY or {}_API_KEY.".format(
            LLM_PROVIDER,
            LLM_PROVIDER.upper(),
        )
    )

# DeepSeek V4 supports thinking and non-thinking modes. Leave this unset to
# use the API default, or set it to "enabled" / "disabled" explicitly.
DEEPSEEK_THINKING = _env("DEEPSEEK_THINKING")
if DEEPSEEK_THINKING not in {None, "enabled", "disabled"}:
    raise ValueError("DEEPSEEK_THINKING must be 'enabled' or 'disabled'.")


DB_HOST = os.getenv("DB_HOST")
DB_PORT = os.getenv("DB_PORT")
DB_USER = os.getenv("DB_USER")
DB_PASSWORD = os.getenv("DB_PASSWORD")
DB_NAME = os.getenv("DB_NAME")

# URL-encode user/password so special characters (@ % ) { } = etc.) don't
# corrupt the connection string.
_USER = quote_plus(DB_USER) if DB_USER else ""
_PASSWORD = quote_plus(DB_PASSWORD) if DB_PASSWORD else ""

DATABASE_URL = (
    f"mysql+pymysql://{_USER}:{_PASSWORD}@{DB_HOST}:{DB_PORT}/{DB_NAME}"
    "?charset=utf8mb4"
)
