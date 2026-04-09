"""Pydantic models for golden test set and benchmark results."""

from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, Field


class ElementCandidate(BaseModel):
    """A navigation element extracted from a page.

    Matches the element dict shape used throughout the verifier pipeline.
    """

    text: str = ""
    href: str = ""
    aria: str = ""
    visible: bool = True
    inNav: bool = False
    inHeader: bool = False
    inFooter: bool = False


class GoldenTestCase(BaseModel):
    """One benchmark test case with a known correct answer."""

    id: str = Field(description="Unique case identifier")
    company_name: str
    url: str
    goal: Literal["careers", "contact"]
    elements: list[ElementCandidate]
    expected_pick_idx: int | None = Field(
        description="Index into the *prepared* candidates list, or None if NONE is correct"
    )
    expected_pick_text: str | None = Field(
        default=None, description="Human-readable label for the expected pick"
    )
    difficulty: Literal["easy", "medium", "hard"] = "medium"
    notes: str = ""


class GoldenTestSet(BaseModel):
    """Collection of test cases for a single goal type."""

    version: str = "1.0"
    goal: Literal["careers", "contact"]
    cases: list[GoldenTestCase]


class CaseResult(BaseModel):
    """Result from running a single golden test case through a model variant."""

    case_id: str
    model_id: str
    quant_level: str
    is_lora: bool
    backend: str = "ollama"
    predicted_idx: int | None
    expected_idx: int | None
    correct: bool
    latency_ms: float
    prompt_tokens: int = 0
    completion_tokens: int = 0
    raw_response: str = ""


class VariantScore(BaseModel):
    """Aggregate scoring for one model variant across all test cases."""

    model_id: str
    quant_level: str
    is_lora: bool
    backend: str = "ollama"

    accuracy: float = 0.0
    precision_by_goal: dict[str, float] = Field(default_factory=dict)
    recall_by_goal: dict[str, float] = Field(default_factory=dict)
    f1_by_goal: dict[str, float] = Field(default_factory=dict)

    # Confusion matrix: {outcome: count}
    # Outcomes: correct_pick, wrong_pick, false_none, true_none
    confusion_matrix: dict[str, int] = Field(default_factory=dict)
    none_rate: float = 0.0
    false_none_rate: float = 0.0
    total_cases: int = 0


class VariantMetrics(BaseModel):
    """Performance metrics for one model variant."""

    model_id: str
    quant_level: str
    is_lora: bool
    backend: str = "ollama"

    latency_p50_ms: float = 0.0
    latency_p95_ms: float = 0.0
    latency_p99_ms: float = 0.0
    latency_mean_ms: float = 0.0

    tokens_per_second: float = 0.0
    model_memory_mb: float = 0.0
    gpu_memory_mb: float | None = None

    estimated_cost_per_1k_queries: float = 0.0


class ParetoPoint(BaseModel):
    """A variant evaluated for Pareto optimality."""

    model_id: str
    quant_level: str
    is_lora: bool
    accuracy: float
    latency_p50_ms: float
    memory_mb: float
    cost_per_1k: float
    is_pareto_optimal: bool = False
