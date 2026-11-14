"""OpenAI-compatible clients: the inference server configured in .env, and the Kaggle Model Proxy."""

import os
from datetime import UTC, datetime
from pathlib import Path

from dotenv import load_dotenv
from openai import OpenAI

KAGGLE_ENV_FILE = Path(".env.kaggle")
KAGGLE_AUTH_COMMAND = f"uvx --with six kaggle benchmarks auth -y --env-file {KAGGLE_ENV_FILE}"


def make_client() -> OpenAI:
    load_dotenv()
    if not os.environ.get("OPENAI_BASE_URL"):
        raise SystemExit("OPENAI_BASE_URL is not set; copy .env.example to .env")
    return OpenAI()


def make_kaggle_proxy_client() -> OpenAI:
    """Client for the hosted models of the Kaggle Model Proxy (KAGGLE.md §9). Its key is valid for two hours."""
    load_dotenv(KAGGLE_ENV_FILE, override=True)
    url, key = os.environ.get("MODEL_PROXY_URL"), os.environ.get("MODEL_PROXY_API_KEY")
    if not url or not key or proxy_key_expired(os.environ.get("MODEL_PROXY_EXPIRY_TIME")):
        raise SystemExit(f"no valid Kaggle Model Proxy key in {KAGGLE_ENV_FILE}; run: {KAGGLE_AUTH_COMMAND}")
    return OpenAI(base_url=url.rstrip("/") + "/openapi", api_key=key)


def proxy_key_expired(expiry: str | None, now: datetime | None = None) -> bool:
    """`expiry` is the ISO time written by `kaggle benchmarks auth`; an unknown expiry counts as valid."""
    if not expiry:
        return False
    return datetime.fromisoformat(expiry.replace("Z", "+00:00")) <= (now or datetime.now(UTC))


def check_model_available(client: OpenAI, model: str) -> None:
    available = {m.id for m in client.models.list()}
    if model not in available:
        raise SystemExit(f"model {model!r} not available on the server; for Ollama run: ollama pull {model}")
