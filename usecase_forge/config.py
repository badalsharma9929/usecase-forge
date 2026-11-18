"""Runtime settings, read from environment variables (or a .env file)."""

from __future__ import annotations

import os
from dataclasses import dataclass

from dotenv import load_dotenv


@dataclass(frozen=True)
class Settings:
    chat_model: str = "gemini-3.8-flash"
    # Used automatically when the main model is overloaded or unavailable.
    fallback_model: str | None = "gemini-3.5-flash"
    embedding_model: str = "models/gemini-embedding-001"
    google_api_key: str | None = None
    jina_api_key: str | None = None
    # The critic must give at least this score (1-10) to approve the plan.
    approval_score: int = 7
    # How many times the strategist may revise its plan after critic feedback.
    max_revisions: int = 2
    # Dataset links kept per use case after the relevance check.
    datasets_per_use_case: int = 3


def load_settings() -> Settings:
    load_dotenv()
    return Settings(
        chat_model=os.getenv("GEMINI_MODEL", Settings.chat_model),
        fallback_model=os.getenv("GEMINI_FALLBACK_MODEL", Settings.fallback_model) or None,
        embedding_model=os.getenv("GEMINI_EMBEDDING_MODEL", Settings.embedding_model),
        google_api_key=os.getenv("GOOGLE_API_KEY") or None,
        jina_api_key=os.getenv("JINA_API_KEY") or None,
        approval_score=int(os.getenv("APPROVAL_SCORE", Settings.approval_score)),
        max_revisions=int(os.getenv("MAX_REVISIONS", Settings.max_revisions)),
        datasets_per_use_case=int(os.getenv("DATASETS_PER_USE_CASE", Settings.datasets_per_use_case)),
    )
