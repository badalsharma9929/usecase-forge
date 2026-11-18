"""Offline fakes: the whole graph runs without network or API keys."""

from __future__ import annotations

from collections import defaultdict, deque

import pytest
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

PAGE = "\n\n".join(
    [
        "BYJU'S is an Indian edtech company offering online learning programs for K-12 students.",
        "We prepare students for competitive exams such as JEE, NEET and UPSC with live classes.",
        "Personalised learning journeys adapt to every student's pace using practice tests.",
        "Parents receive progress reports, and doubt-solving is available 24x7 from tutors.",
    ]
    * 6
)


class FakeLLM:
    """Returns queued answers per output schema and records every prompt."""

    def __init__(self):
        self.queues: dict[type, deque] = defaultdict(deque)
        self.prompts: dict[type, list[str]] = defaultdict(list)

    def queue(self, schema: type, *answers):
        self.queues[schema].extend(answers)
        return self

    def with_structured_output(self, schema):
        llm = self

        class Runner:
            def invoke(self, messages):
                llm.prompts[schema].append(messages[-1][1])
                answer = llm.queues[schema].popleft()
                return answer(messages) if callable(answer) else answer.model_copy(deep=True)

        return Runner()


def make_use_case(title: str, evidence=("S1",)) -> UseCase:
    return UseCase(
        title=title,
        department="Product",
        objective="Help students learn faster",
        ai_approach="Knowledge tracing model on practice-test answers",
        business_impact="Raise weekly active learners by 10%",
        evidence=list(evidence),
        dataset_keywords=["student performance", "exam questions"],
    )


PROFILE = CompanyProfile(
    name="BYJU'S",
    industry="EdTech",
    summary="Online learning programs for school students and exam aspirants.",
    products_and_services=["K-12 classes", "JEE/NEET coaching"],
    customers=["students", "parents"],
    pain_points=["keeping students engaged", "doubt resolution at scale"],
)


def critique(score: int) -> Critique:
    return Critique(score=score, strengths=["clear"], problems=[] if score >= 7 else ["too generic"],
                    feedback="Tie each idea to exam prep data.")


@pytest.fixture
def settings():
    return Settings(google_api_key="fake", approval_score=7, max_revisions=2, datasets_per_use_case=2)


@pytest.fixture
def datasets_calls():
    return []


@pytest.fixture
def fake_search(datasets_calls):
    def search(keyword: str) -> list[DatasetCandidate]:
        datasets_calls.append(keyword)
        slug = keyword.replace(" ", "-")
        return [
            DatasetCandidate(source="Hugging Face", name=f"org/{slug}", url=f"https://hf.co/{slug}",
                             downloads=100, keyword=keyword),
            DatasetCandidate(source="Kaggle", name=f"{slug} junk", url=f"https://kaggle.com/{slug}-junk",
                             downloads=999, keyword=keyword),
        ]

    return search


def judge_relevant_hf(messages) -> DatasetJudgement:
    """Mark Hugging Face candidates relevant and Kaggle 'junk' ones not."""
    urls = [line.split(" | ")[0][2:] for line in messages[-1][1].splitlines() if line.startswith("- ")]
    return DatasetJudgement(verdicts=[DatasetVerdict(url=u, relevant="junk" not in u, reason="matches task")
                                      for u in urls])


@pytest.fixture
def make_deps(settings, fake_search):
    def factory(llm: FakeLLM, fetch=lambda url: PAGE, search=None) -> Dependencies:
        return Dependencies(
            llm=llm,
            embeddings=DeterministicFakeEmbedding(size=32),
            fetch_page=fetch,
            search_datasets=search or fake_search,
            settings=settings,
        )

    return factory


__all__ = ["FakeLLM", "PROFILE", "UseCasePlan", "critique", "judge_relevant_hf", "make_use_case"]
