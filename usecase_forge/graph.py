"""The pipeline's control flow, defined once and used two ways:

* ``build_graph`` / ``stream_pipeline`` run it in-process with LangGraph (CLI, local dev).
* ``run_step`` executes a single agent, so the web deployment can run each step in its
  own short serverless invocation and persist state in between.
"""

from __future__ import annotations

from functools import partial
from typing import Iterator

from langgraph.graph import END, START, StateGraph

from usecase_forge import agents
from usecase_forge.config import Settings, load_settings
from usecase_forge.state import Dependencies, PipelineState, apply_update

STEPS = ("researcher", "strategist", "critic", "dataset_scout", "reporter")
FIRST_STEP = STEPS[0]


def next_step(step: str, state: PipelineState, deps: Dependencies) -> str | None:
    """Which agent runs after `step`, or None when the pipeline is finished."""
    if step == "critic":
        return agents.after_critic(state, deps)
    following = {"researcher": "strategist", "strategist": "critic", "dataset_scout": "reporter"}
    return following.get(step)


def run_step(step: str, state: PipelineState, deps: Dependencies) -> tuple[PipelineState, str | None]:
    if step not in STEPS:
        raise ValueError(f"Unknown step {step!r}")
    update = getattr(agents, step)(state, deps)
    new_state = apply_update(state, update)
    return new_state, next_step(step, new_state, deps)


def build_graph(deps: Dependencies):
    g = StateGraph(PipelineState)
    for name in STEPS:
        g.add_node(name, partial(getattr(agents, name), deps=deps))
    g.add_edge(START, FIRST_STEP)
    for name in STEPS:
        targets = {s for s in STEPS} | {END}
        g.add_conditional_edges(
            name,
            lambda state, _name=name: next_step(_name, state, deps) or END,
            list(targets),
        )
    return g.compile()


class FallbackChatModel:
    """Structured-output chat that tries each model in order until one answers."""

    def __init__(self, models: list):
        self.models = models

    def with_structured_output(self, schema: type):
        primary, *rest = [m.with_structured_output(schema) for m in self.models]
        return primary.with_fallbacks(rest) if rest else primary


class MissingApiKeyError(RuntimeError):
    pass


def default_dependencies(settings: Settings | None = None, api_key: str | None = None) -> Dependencies:
    """Real Gemini, Jina and dataset-hub clients.

    `api_key` overrides the server's key (used for bring-your-own-key runs).
    """
    from langchain_google_genai import ChatGoogleGenerativeAI, GoogleGenerativeAIEmbeddings

    from usecase_forge.tools.datasets import search_datasets
    from usecase_forge.tools.web import fetch_page

    settings = settings or load_settings()
    key = api_key or settings.google_api_key
    if not key:
        raise MissingApiKeyError("No Gemini API key. Set GOOGLE_API_KEY in .env or provide your own key.")

    def chat(model: str):
        # Few retries per model so an overloaded model hands over to the fallback quickly.
        return ChatGoogleGenerativeAI(model=model, temperature=0.4, api_key=key, max_retries=2)

    models = [chat(settings.chat_model)]
    if settings.fallback_model and settings.fallback_model != settings.chat_model:
        models.append(chat(settings.fallback_model))
    return Dependencies(
        llm=FallbackChatModel(models),
        embeddings=GoogleGenerativeAIEmbeddings(model=settings.embedding_model, api_key=key),
        fetch_page=partial(fetch_page, api_key=settings.jina_api_key),
        search_datasets=search_datasets,
        settings=settings,
    )


def initial_state(url: str, extra_urls: list[str] | None = None) -> PipelineState:
    return {"url": url, "extra_urls": extra_urls or [], "revisions": 0, "scores": [], "log": []}


def stream_pipeline(url: str, deps: Dependencies, extra_urls: list[str] | None = None) -> Iterator[PipelineState]:
    """Yield the full state after every agent step (useful for live progress)."""
    graph = build_graph(deps)
    # Each strategist/critic round is 2 steps; leave headroom for the revision loop.
    limit = 10 + 2 * deps.settings.max_revisions
    yield from graph.stream(initial_state(url, extra_urls), stream_mode="values", config={"recursion_limit": limit})


def run_pipeline(url: str, deps: Dependencies, extra_urls: list[str] | None = None) -> PipelineState:
    state: PipelineState = {}
    for state in stream_pipeline(url, deps, extra_urls):
        pass
    return state
