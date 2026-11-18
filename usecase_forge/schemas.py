"""Typed data passed between agents.

The LLM is forced to answer in these shapes (structured output), so no agent
ever parses free-form text with string splitting.
"""

from __future__ import annotations

from pydantic import BaseModel, Field


class CompanyProfile(BaseModel):
    name: str = Field(description="Company or brand name")
    industry: str = Field(description="Primary industry, e.g. 'EdTech' or 'Automotive manufacturing'")
    summary: str = Field(description="2-3 sentence summary of what the company does")
    products_and_services: list[str] = Field(description="Main products or services")
    customers: list[str] = Field(description="Main customer segments")
    pain_points: list[str] = Field(
        description="Operational or customer problems that AI could plausibly address, inferred from the source"
    )


class UseCase(BaseModel):
    title: str
    department: str = Field(description="Owning team, e.g. Marketing, Operations, Customer Support")
    objective: str = Field(description="The business problem and what success looks like")
    ai_approach: str = Field(description="Concrete technique: model type, data needed, how it is used")
    business_impact: str = Field(description="Expected impact, ideally with a measurable KPI")
    evidence: list[str] = Field(
        description="Source IDs such as 'S3' from the provided context that support this use case"
    )
    dataset_keywords: list[str] = Field(
        description="3-5 short keyword phrases for searching public datasets (Kaggle / Hugging Face)"
    )


class UseCasePlan(BaseModel):
    use_cases: list[UseCase]


class Critique(BaseModel):
    score: int = Field(description="Overall quality from 1 (poor) to 10 (excellent)")
    strengths: list[str]
    problems: list[str] = Field(description="Specific, actionable problems; empty if none")
    feedback: str = Field(description="Instructions for the strategist on how to improve the plan")


class DatasetCandidate(BaseModel):
    source: str  # "Hugging Face" or "Kaggle"
    name: str
    url: str
    downloads: int | None = None
    keyword: str = ""


class DatasetVerdict(BaseModel):
    url: str
    relevant: bool
    reason: str = Field(description="One short sentence on why it fits or does not fit")


class DatasetJudgement(BaseModel):
    verdicts: list[DatasetVerdict]


class RecommendedDataset(DatasetCandidate):
    reason: str


class UseCaseResult(BaseModel):
    use_case: UseCase
    datasets: list[RecommendedDataset]


class Source(BaseModel):
    id: str
    url: str
    excerpt: str
