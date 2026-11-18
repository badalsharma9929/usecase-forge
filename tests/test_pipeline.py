import pytest

from usecase_forge.graph import run_pipeline
from usecase_forge.schemas import CompanyProfile, Critique, DatasetJudgement, UseCasePlan
from usecase_forge.tools.web import ScrapeError

from .conftest import PROFILE, FakeLLM, critique, judge_relevant_hf, make_use_case


def plan(*titles, evidence=("S1",)):
    return UseCasePlan(use_cases=[make_use_case(t, evidence) for t in titles])


def test_critic_rejection_triggers_revision_with_feedback(make_deps):
    llm = (
        FakeLLM()
        .queue(CompanyProfile, PROFILE)
        .queue(UseCasePlan, plan("Generic chatbot"), plan("Adaptive JEE practice", "Doubt-solving copilot"))
        .queue(Critique, critique(4), critique(8))
        .queue(DatasetJudgement, judge_relevant_hf, judge_relevant_hf)
    )
    state = run_pipeline("https://byjus.com", make_deps(llm))

    assert state["scores"] == [4, 8]
    assert len(llm.prompts[UseCasePlan]) == 2
    revision_prompt = llm.prompts[UseCasePlan][1]
    assert "scored 4/10" in revision_prompt and "Tie each idea to exam prep data." in revision_prompt
    assert [r.use_case.title for r in state["results"]] == ["Adaptive JEE practice", "Doubt-solving copilot"]
    assert "# GenAI & ML Use Cases for BYJU'S" in state["report"]
    assert "Reviewer score:** 8/10 (rounds: 4 -> 8)" in state["report"]


def test_revision_loop_stops_at_budget(make_deps, settings):
    attempts = settings.max_revisions + 1
    llm = (
        FakeLLM()
        .queue(CompanyProfile, PROFILE)
        .queue(UseCasePlan, *[plan(f"Idea v{i}") for i in range(attempts)])
        .queue(Critique, *[critique(3)] * attempts)
        .queue(DatasetJudgement, judge_relevant_hf)
    )
    state = run_pipeline("https://byjus.com", make_deps(llm))

    assert len(llm.prompts[UseCasePlan]) == attempts
    assert state["scores"] == [3] * attempts
    assert "report" in state  # still ships the best effort


def test_hallucinated_citations_are_removed(make_deps):
    llm = (
        FakeLLM()
        .queue(CompanyProfile, PROFILE)
        .queue(UseCasePlan, plan("Adaptive practice", evidence=("S1", "[S2]", "S999")))
        .queue(Critique, critique(9))
        .queue(DatasetJudgement, judge_relevant_hf)
    )
    state = run_pipeline("https://byjus.com", make_deps(llm))

    retrieved = {s.id for s in state["sources"]}
    evidence = state["results"][0].use_case.evidence
    assert "S999" not in evidence
    assert set(evidence) <= retrieved
    assert all(not e.startswith("[") for e in evidence)


def test_dataset_scout_keeps_only_relevant_and_limits_count(make_deps, datasets_calls):
    llm = (
        FakeLLM()
        .queue(CompanyProfile, PROFILE)
        .queue(UseCasePlan, plan("Adaptive practice"))
        .queue(Critique, critique(9))
        .queue(DatasetJudgement, judge_relevant_hf)
    )
    state = run_pipeline("https://byjus.com", make_deps(llm))

    datasets = state["results"][0].datasets
    assert datasets and all(d.source == "Hugging Face" for d in datasets)
    assert len(datasets) <= 2  # datasets_per_use_case in the test settings
    assert datasets_calls == ["student performance", "exam questions"]


def test_dataset_search_failure_does_not_stop_pipeline(make_deps):
    llm = FakeLLM().queue(CompanyProfile, PROFILE).queue(UseCasePlan, plan("Adaptive practice")) \
        .queue(Critique, critique(9))
    state = run_pipeline("https://byjus.com", make_deps(llm, search=lambda kw: []))

    assert state["results"][0].datasets == []
    assert "No relevant public dataset found" in state["report"]


def test_extra_pages_are_indexed(make_deps):
    fetched = []

    def fetch(url):
        fetched.append(url)
        return f"Content from {url}\n\n" + "detail " * 200

    llm = FakeLLM().queue(CompanyProfile, PROFILE).queue(UseCasePlan, plan("Idea")) \
        .queue(Critique, critique(9)).queue(DatasetJudgement, judge_relevant_hf)
    run_pipeline("https://byjus.com", make_deps(llm, fetch=fetch), extra_urls=["https://byjus.com/about"])
    assert fetched == ["https://byjus.com", "https://byjus.com/about"]


def test_scrape_error_propagates(make_deps):
    def fetch(url):
        raise ScrapeError("blocked")

    with pytest.raises(ScrapeError):
        run_pipeline("https://byjus.com", make_deps(FakeLLM(), fetch=fetch))
