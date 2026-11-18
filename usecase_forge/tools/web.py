"""Fetch a web page as clean Markdown through the Jina Reader API."""

from __future__ import annotations

import re

import requests


class ScrapeError(RuntimeError):
    pass


_IMAGE = re.compile(r"!\[[^\]]*\]\([^)]*\)")
_LINK = re.compile(r"\[([^\]]*)\]\([^)]*\)")
_URL = re.compile(r"https?://\S+")
_SPACES = re.compile(r"[ \t]+")


def clean_markdown(text: str) -> str:
    """Strip images, link targets and bare URLs so chunks hold readable text.

    Navigation-heavy pages are often mostly URLs, which wastes the LLM's context
    and makes retrieval match on noise.
    """
    text = _IMAGE.sub("", text)
    text = _LINK.sub(r"\1", text)
    text = _URL.sub("", text)
    lines = [_SPACES.sub(" ", line).strip() for line in text.splitlines()]
    # Keep paragraph breaks, drop lines that are now just punctuation.
    kept = [line if re.search(r"\w", line) else "" for line in lines]
    return re.sub(r"\n{3,}", "\n\n", "\n".join(kept)).strip()


def fetch_page(url: str, api_key: str | None = None, timeout: float = 60) -> str:
    headers = {"Authorization": f"Bearer {api_key}"} if api_key else {}
    try:
        response = requests.get(f"https://r.jina.ai/{url}", headers=headers, timeout=timeout)
        response.raise_for_status()
    except requests.RequestException as exc:
        raise ScrapeError(f"Could not fetch {url}: {exc}") from exc
    text = clean_markdown(response.text)
    if len(text) < 200:
        raise ScrapeError(f"{url} returned almost no text ({len(text)} characters)")
    return text
