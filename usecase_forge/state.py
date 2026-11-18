"""Shared pipeline state, its JSON codec, and the dependencies injected into agents."""

from __future__ import annotations

import operator
from dataclasses import dataclass
from typing import Annotated, Any, Callable, TypedDict

from langchain_core.embeddings import Embeddings
from pydantic import BaseModel, TypeAdapter

from usecase_forge.config import Settings
from usecase_forge.schemas import (
    CompanyProfile,
    Critique,
    DatasetCandidate,
    Source,
    UseCasePlan,
    UseCaseResult,
)


class PipelineState(TypedDict, total=False):
    url: str
    extra_urls: list[str]
    profile: CompanyProfile
    sources: list[Source]
    plan: UseCasePlan
    critique: Critique
    revisions: int
    scores: Annotated[list[int], operator.add]  # critic score per round
    results: list[UseCaseResult]
    report: str
    log: Annotated[list[str], operator.add]


# Keys whose updates are appended rather than replaced (mirrors the Annotated reducers).
APPEND_KEYS = frozenset({"scores", "log"})

# Typed keys and how to rebuild them from JSON.
_ADAPTERS: dict[str, TypeAdapter] = {
    "profile": TypeAdapter(CompanyProfile),
    "sources": TypeAdapter(list[Source]),
    "plan": TypeAdapter(UseCasePlan),
    "critique": TypeAdapter(Critique),
    "results": TypeAdapter(list[UseCaseResult]),
}


def apply_update(state: PipelineState, update: dict) -> PipelineState:
    merged: dict = dict(state)
    for key, value in update.items():
        merged[key] = [*merged.get(key, []), *value] if key in APPEND_KEYS else value
    return merged  # type: ignore[return-value]


def dump_state(state: PipelineState) -> dict:
    """Convert pipeline state to plain JSON-compatible data."""
    out: dict = {}
    for key, value in state.items():
        if key in _ADAPTERS:
            out[key] = _ADAPTERS[key].dump_python(value, mode="json")
        elif isinstance(value, BaseModel):
            out[key] = value.model_dump(mode="json")
        else:
            out[key] = value
    return out


def load_state(data: dict) -> PipelineState:
    return {  # type: ignore[return-value]
        key: _ADAPTERS[key].validate_python(value) if key in _ADAPTERS else value
        for key, value in data.items()
    }


@dataclass
class Dependencies:
    """Everything that talks to the outside world. Tests swap these for fakes."""

    llm: Any  # a LangChain chat model (needs .with_structured_output)
    embeddings: Embeddings
    fetch_page: Callable[[str], str]
    search_datasets: Callable[[str], list[DatasetCandidate]]
    settings: Settings
