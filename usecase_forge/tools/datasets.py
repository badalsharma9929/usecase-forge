"""Search public dataset hubs. Each source fails soft: an outage or missing
credentials returns no results instead of stopping the pipeline."""

from __future__ import annotations

import contextlib
import io
import logging
import os
from pathlib import Path

from huggingface_hub import HfApi

from usecase_forge.schemas import DatasetCandidate

log = logging.getLogger(__name__)


def search_huggingface(keyword: str, limit: int = 3) -> list[DatasetCandidate]:
    results = HfApi().list_datasets(search=keyword, sort="downloads", limit=limit)
    return [
        DatasetCandidate(
            source="Hugging Face",
            name=d.id,
            url=f"https://huggingface.co/datasets/{d.id}",
            downloads=d.downloads,
            keyword=keyword,
        )
        for d in results
    ]


def kaggle_configured() -> bool:
    home = Path.home() / ".kaggle"
    return bool(
        os.getenv("KAGGLE_API_TOKEN")
        or (os.getenv("KAGGLE_USERNAME") and os.getenv("KAGGLE_KEY"))
        or (home / "kaggle.json").exists()
        or (home / "access_token").exists()
    )


def search_kaggle(keyword: str, limit: int = 3) -> list[DatasetCandidate]:
    if not kaggle_configured():
        return []
    # Importing kaggle authenticates immediately and prints to stdout; keep it quiet.
    with contextlib.redirect_stdout(io.StringIO()):
        from kaggle.api.kaggle_api_extended import KaggleApi

        api = KaggleApi()
        api.authenticate()
        found = api.dataset_list(search=keyword, sort_by="votes") or []
    return [
        DatasetCandidate(
            source="Kaggle",
            name=getattr(d, "title", None) or d.ref,
            url=f"https://www.kaggle.com/datasets/{d.ref}",
            downloads=getattr(d, "download_count", None) or getattr(d, "downloadCount", None),
            keyword=keyword,
        )
        for d in found[:limit]
    ]


FILLER_WORDS = {"dataset", "datasets", "data", "logs", "log", "records", "corpus"}


def keyword_variants(keyword: str) -> list[str]:
    """The cleaned keyword, then its two-word windows as broader fallbacks.

    Hugging Face search matches dataset *names*, so 'lead conversion dataset'
    finds nothing while 'lead conversion' or 'lead scoring' does.
    """
    words = [w for w in keyword.lower().split() if w not in FILLER_WORDS]
    if not words:
        return []
    variants = [" ".join(words)]
    if len(words) > 2:
        variants += [" ".join(words[i : i + 2]) for i in range(len(words) - 1)]
    return variants


def _safe(search, keyword: str, limit: int) -> list[DatasetCandidate]:
    try:
        return search(keyword, limit)
    except (Exception, SystemExit) as exc:  # kaggle calls sys.exit on bad credentials
        log.warning("%s failed for %r: %s", search.__name__, keyword, exc)
        return []


def search_datasets(keyword: str, limit: int = 3) -> list[DatasetCandidate]:
    found: list[DatasetCandidate] = []
    for search in (search_huggingface, search_kaggle):
        for variant in keyword_variants(keyword):
            hits = _safe(search, variant, limit)
            if hits:
                found.extend(hits)
                break  # stop at the most specific variant that matches
    return found
