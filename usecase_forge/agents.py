"""The five agents. Each is a LangGraph node: it reads the shared state and
returns only the keys it changes.

    researcher -> strategist <-> critic -> dataset_scout -> reporter
"""

from __future__ import annotations

from typing import Any

from usecase_forge.rag import KnowledgeBase, format_context
from usecase_forge.schemas import (
    CompanyProfile,
    Critique,
    DatasetCandidate,
    DatasetJudgement,
    RecommendedDataset,
    UseCasePlan,
    UseCaseResult,
)
from usecase_forge.state import Dependencies, PipelineState

PROFILE_CHARS = 12_000  # how much raw page text the researcher reads directly
KEYWORDS_PER_USE_CASE = 4


def _ask(deps: Dependencies, schema: type, system: str, human: str) -> Any:
    return deps.llm.with_structured_output(schema).invoke([("system", system), ("human", human)])


# --- 1. Researcher ---------------------------------------------------------

RESEARCHER_SYSTEM = """You are a business analyst. Build a factual profile of a company
from its own website. Use only what the text supports; when you infer pain points,
keep them plausible for this specific business. Never invent numbers."""


def _retrieval_queries(profile: CompanyProfile) -> list[str]:
    return [
        profile.summary,
        *profile.products_and_services[:4],
        *profile.pain_points[:4],
        f"{profile.name} customers {' '.join(profile.customers[:3])}",
    ]


def researcher(state: PipelineState, deps: Dependencies) -> dict:
    """Read the pages, profile the company, and pick the evidence the later agents use.

    Retrieval happens here, once: the queries depend only on the profile, so every
    strategist/critic round sees the same sources. This keeps later steps free of the
    vector index, which lets each step run in a separate serverless invocation.
    """
    kb = KnowledgeBase(deps.embeddings)
    urls = [state["url"], *state.get("extra_urls", [])]
    texts = []
    for url in urls:
        text = deps.fetch_page(url)
        kb.add_page(url, text)
        texts.append(f"## Page: {url}\n{text}")
    corpus = "\n\n".join(texts)[:PROFILE_CHARS]
    profile: CompanyProfile = _ask(deps, CompanyProfile, RESEARCHER_SYSTEM, corpus)
    sources = kb.retrieve(_retrieval_queries(profile), k=3)
    return {
        "profile": profile,
        "sources": sources,
        "log": [f"Researcher: read {len(urls)} page(s), {len(kb)} chunks indexed; "
                f"identified {profile.name} ({profile.industry})"],
    }


# --- 2. Strategist ---------------------------------------------------------

STRATEGIST_SYSTEM = """You are a senior AI solutions architect. Propose 4-5 Generative AI / ML
use cases for the company below.

Rules:
- Each use case must be specific to THIS company's products, customers or pain points,
  not a generic idea any company could use.
- Cover at least three different departments.
- Ground each one in the numbered sources: list the source IDs (e.g. "S3") that
  support it in `evidence`. Only use IDs that appear in the context.
- `ai_approach` must name a concrete technique and the data it needs.
- `business_impact` should name a KPI that would move.
- `dataset_keywords` are 1-3 word topic names that public datasets are commonly named
  after, e.g. "lead scoring", "student performance", "math word problems". Do not
  include words like "dataset" or "data"."""


def strategist(state: PipelineState, deps: Dependencies) -> dict:
    profile = state["profile"]
    sources = state["sources"]
    prompt = (
        f"Company profile:\n{profile.model_dump_json(indent=2)}\n\n"
        f"Context from the company's website:\n{format_context(sources)}"
    )
    critique = state.get("critique")
    if critique is not None:
        prompt += (
            f"\n\nYour previous plan scored {critique.score}/10. Reviewer feedback:\n"
            f"{critique.feedback}\nProblems: {'; '.join(critique.problems) or 'none listed'}\n"
            f"Previous plan:\n{state['plan'].model_dump_json(indent=2)}\n"
            "Produce an improved plan that fixes every problem."
        )
    plan: UseCasePlan = _ask(deps, UseCasePlan, STRATEGIST_SYSTEM, prompt)

    # Guard against hallucinated citations: keep only IDs that were really retrieved.
    valid = {s.id for s in sources}
    for uc in plan.use_cases:
        uc.evidence = [e.strip("[] ") for e in uc.evidence if e.strip("[] ") in valid]

    attempt = state.get("revisions", 0) + 1
    return {
        "plan": plan,
        "log": [f"Strategist: drafted {len(plan.use_cases)} use cases (attempt {attempt})"],
    }


# --- 3. Critic -------------------------------------------------------------

CRITIC_SYSTEM = """You are a demanding reviewer of AI strategy proposals. Score the plan
from 1 to 10 using this rubric:
- Specificity: tailored to this company, not generic (most important).
- Grounding: claims are supported by the cited sources.
- Feasibility: technique and data are realistic for this company.
- Coverage: spans several departments without duplicates.
- Impact: clear, measurable business value.
Give concrete, actionable feedback. A plan full of generic ideas must not score above 6."""


def critic(state: PipelineState, deps: Dependencies) -> dict:
    prompt = (
        f"Company profile:\n{state['profile'].model_dump_json(indent=2)}\n\n"
        f"Sources the strategist could use:\n{format_context(state['sources'])}\n\n"
        f"Plan to review:\n{state['plan'].model_dump_json(indent=2)}"
    )
    review: Critique = _ask(deps, Critique, CRITIC_SYSTEM, prompt)
    review.score = max(1, min(10, review.score))
    approved = review.score >= deps.settings.approval_score
    return {
        "critique": review,
        "revisions": state.get("revisions", 0) + (0 if approved else 1),
        "scores": [review.score],
        "log": [f"Critic: scored {review.score}/10 - {'approved' if approved else 'sent back for revision'}"],
    }


def after_critic(state: PipelineState, deps: Dependencies) -> str:
    if state["critique"].score >= deps.settings.approval_score:
        return "dataset_scout"
    if state["revisions"] > deps.settings.max_revisions:
        return "dataset_scout"  # out of revision budget: ship the best effort
    return "strategist"


# --- 4. Dataset scout ------------------------------------------------------

SCOUT_SYSTEM = """You check whether public datasets could realistically be used to
prototype an AI use case before the company's own data is available.

Mark a dataset relevant if it fits the TASK or a key component of the approach, even
when it comes from a different company or industry (e.g. generic customer-support
dialogues are useful for prototyping an EdTech support bot; student-performance data
is useful for knowledge tracing).
Mark it not relevant if it is about an unrelated task, is a lead or contact list for
sale, a benchmark of an unrelated skill, or the name gives no clue what it contains.
Judge every URL you are given."""


def dataset_scout(state: PipelineState, deps: Dependencies) -> dict:
    results: list[UseCaseResult] = []
    for uc in state["plan"].use_cases:
        candidates: dict[str, DatasetCandidate] = {}
        for keyword in uc.dataset_keywords[:KEYWORDS_PER_USE_CASE]:
            for c in deps.search_datasets(keyword):
                candidates.setdefault(c.url, c)

        chosen: list[RecommendedDataset] = []
        if candidates:
            listing = "\n".join(f"- {c.url} | {c.name} | found via '{c.keyword}'" for c in candidates.values())
            judgement: DatasetJudgement = _ask(
                deps, DatasetJudgement, SCOUT_SYSTEM,
                f"Use case: {uc.title}\nObjective: {uc.objective}\nApproach: {uc.ai_approach}\n\n"
                f"Candidate datasets:\n{listing}",
            )
            for v in judgement.verdicts:
                if v.relevant and v.url in candidates:
                    chosen.append(RecommendedDataset(**candidates[v.url].model_dump(), reason=v.reason))
        chosen.sort(key=lambda d: d.downloads or 0, reverse=True)
        results.append(UseCaseResult(use_case=uc, datasets=chosen[: deps.settings.datasets_per_use_case]))

    total = sum(len(r.datasets) for r in results)
    return {"results": results, "log": [f"Dataset scout: kept {total} relevant datasets"]}


# --- 5. Reporter (no LLM) --------------------------------------------------

def reporter(state: PipelineState, deps: Dependencies) -> dict:
    profile = state["profile"]
    lines = [
        f"# GenAI & ML Use Cases for {profile.name}",
        "",
        f"**Industry:** {profile.industry}  ",
        f"**Source:** {state['url']}  ",
        f"**Reviewer score:** {state['critique'].score}/10 "
        f"(rounds: {' -> '.join(str(s) for s in state.get('scores', []))})",
        "",
        profile.summary,
        "",
    ]
    for i, r in enumerate(state["results"], 1):
        uc = r.use_case
        cites = ", ".join(f"[{e}]" for e in uc.evidence) or "none"
        lines += [
            f"## {i}. {uc.title}",
            f"- **Department:** {uc.department}",
            f"- **Objective:** {uc.objective}",
            f"- **AI approach:** {uc.ai_approach}",
            f"- **Business impact:** {uc.business_impact}",
            f"- **Evidence:** {cites}",
            "",
            "**Datasets to prototype with:**",
        ]
        if r.datasets:
            lines += [f"- [{d.name}]({d.url}) ({d.source}) - {d.reason}" for d in r.datasets]
        else:
            lines.append("- No relevant public dataset found; plan to collect in-house data.")
        lines.append("")

    cited = {e for r in state["results"] for e in r.use_case.evidence}
    if cited:
        lines += ["## Sources", ""]
        for s in state["sources"]:
            if s.id in cited:
                excerpt = " ".join(s.excerpt.split())[:200]
                lines.append(f"- **[{s.id}]** {s.url} - \"{excerpt}...\"")
    return {"report": "\n".join(lines) + "\n", "log": ["Reporter: report ready"]}
