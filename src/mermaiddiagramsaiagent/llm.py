"""OpenAI-compatible client for the inference server configured in .env (see .env.example)."""

import os

from dotenv import load_dotenv
from openai import OpenAI


def make_client() -> OpenAI:
    load_dotenv()
    if not os.environ.get("OPENAI_BASE_URL"):
        raise SystemExit("OPENAI_BASE_URL is not set; copy .env.example to .env")
    return OpenAI()


def check_model_available(client: OpenAI, model: str) -> None:
    available = {m.id for m in client.models.list()}
    if model not in available:
        raise SystemExit(f"model {model!r} not available on the server; for Ollama run: ollama pull {model}")
