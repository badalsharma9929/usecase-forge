"""Offline demo dependencies (DEMO_MODE=1): canned agent answers, no API calls.

Used for UI development and end-to-end checks without spending Gemini quota.
The first plan is deliberately weak so the critic's revision loop is visible.
"""

from __future__ import annotations

import time

from langchain_core.embeddings import DeterministicFakeEmbedding

from usecase_forge.config import Settings
from usecase_forge.schemas import (
    CompanyProfile,
    Critique,
    DatasetCandidate,
    DatasetJudgement,
    DatasetVerdict,
    UseCase,
    UseCasePlan,
)
from usecase_forge.state import Dependencies

PAGE = "\n\n".join([
    "Acme Learning offers live online tutoring for school students in grades 4 to 12.",
    "Our two-teacher model pairs a lead teacher with a doubt-solving assistant in every class.",
    "Students prepare for JEE and NEET with weekly mock tests and personalised revision plans.",
    "Parents get progress reports on WhatsApp after every test.",
    "Book a free demo class at a centre near you or online, morning, afternoon or evening.",
] * 3)

PROFILE = CompanyProfile(
    name="Acme Learning",
    industry="EdTech",
    summary="Acme Learning runs live online and centre-based tutoring for grades 4-12, "
            "with exam preparation for JEE and NEET.",
    products_and_services=["Live tutoring", "JEE/NEET test series", "Free demo classes"],
    customers=["School students", "Parents"],
    pain_points=["Answering student doubts during live classes", "Demo class no-shows"],
)


def _uc(title, dept, keywords, evidence=("S1", "S2")) -> UseCase:
    return UseCase(
        title=title, department=dept,
        objective=f"{title} to improve learning outcomes and operations.",
        ai_approach="Gradient-boosted model on historical interaction data, with an LLM for explanations.",
        business_impact="Lift weekly active learners by 10% within two terms.",
        evidence=list(evidence), dataset_keywords=keywords,
    )


DRAFT = UseCasePlan(use_cases=[
    _uc("General AI chatbot", "Customer Support", ["chatbot"]),
    _uc("Marketing content generator", "Marketing", ["marketing copy"]),
    _uc("Sales forecasting", "Sales", ["sales forecast"]),
])

REVISED = UseCasePlan(use_cases=[
    _uc("Live-class doubt assistant for the second teacher", "Academics", ["math word problems", "student questions"]),
    _uc("Adaptive JEE/NEET mock-test sequencing", "Product", ["student performance", "knowledge tracing"]),
    _uc("Demo-class no-show prediction", "Operations", ["appointment no show"]),
    _uc("WhatsApp progress summaries for parents", "Customer Support", ["text summarization"]),
])


class _Runner:
    def __init__(self, schema, delay):
        self.schema, self.delay = schema, delay

    def invoke(self, messages):
        time.sleep(self.delay)
        prompt = messages[-1][1]
        if self.schema is CompanyProfile:
            return PROFILE
        if self.schema is UseCasePlan:
            return (REVISED if "previous plan scored" in prompt else DRAFT).model_copy(deep=True)
        if self.schema is Critique:
            if "General AI chatbot" in prompt:
                return Critique(score=5, strengths=["Covers several departments"],
                                problems=["Ideas are generic and not tied to the tutoring model"],
                                feedback="Tie every idea to live classes, exam prep or demo bookings.")
            return Critique(score=8, strengths=["Specific to the two-teacher model", "Clear KPIs"],
                            problems=[], feedback="Good.")
        if self.schema is DatasetJudgement:
            urls = [line.split(" | ")[0][2:] for line in prompt.splitlines() if line.startswith("- ")]
            return DatasetJudgement(verdicts=[
                DatasetVerdict(url=u, relevant="noise" not in u, reason="Matches the task for a quick prototype.")
                for u in urls])
        raise ValueError(f"Demo has no answer for {self.schema.__name__}")


class DemoLLM:
    def __init__(self, delay: float):
        self.delay = delay

    def with_structured_output(self, schema):
        return _Runner(schema, self.delay)


def _search(keyword: str) -> list[DatasetCandidate]:
    slug = keyword.replace(" ", "-")
    return [
        DatasetCandidate(source="Hugging Face", name=f"demo/{slug}", url=f"https://huggingface.co/datasets/demo/{slug}",
                         downloads=1200, keyword=keyword),
        DatasetCandidate(source="Kaggle", name=f"{slug} noise", url=f"https://www.kaggle.com/datasets/demo/{slug}-noise",
                         downloads=50, keyword=keyword),
    ]


def demo_dependencies(_api_key: str | None = None, delay: float = 1.5) -> Dependencies:
    return Dependencies(
        llm=DemoLLM(delay),
        embeddings=DeterministicFakeEmbedding(size=32),
        fetch_page=lambda url: PAGE,
        search_datasets=_search,
        settings=Settings(google_api_key="demo"),
    )
