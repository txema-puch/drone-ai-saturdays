"""Typed public API contracts for aggregate research evidence."""

from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, ConfigDict

AggregateCell = int | Literal["<10", "suppressed"]
CountMap = dict[str, AggregateCell]
CriterionCountMap = dict[str, CountMap]


class _ClosedContract(BaseModel):
    model_config = ConfigDict(extra="forbid")


class ResearchCohortResponse(_ClosedContract):
    cohort_id: str
    period: str
    role: str
    source_sha256: str
    base_reference_sha256: str
    context_reference_sha256: str | None
    rows: int | None
    operations: int
    operations_with_attempts: int | None
    attempts: int
    assessable_attempts: int
    abstention_rate: float | None
    review_rate_among_assessable: float | None
    status_counts: CountMap
    outcome_counts: CountMap | None
    criterion_status_counts: CriterionCountMap
    runway_direction_counts: CountMap | None
    context_coverage: dict[str, float] | None
    decision: str
    interpretation_limits: list[str]


class ScreeningHoldoutFindingResponse(_ClosedContract):
    cohort_id: str
    policy: str
    reason_counts: CountMap
    criterion_status_counts: CriterionCountMap
    interpretation_limits: list[str]


class ContextValidationFindingResponse(_ClosedContract):
    cohort_id: str
    base_status_counts: CountMap
    context_status_counts: CountMap
    base_criterion_status_counts: CriterionCountMap
    context_criterion_status_counts: CriterionCountMap
    base_review_rate_among_assessable: float | None
    context_review_rate_among_assessable: float | None
    review_overlap: CountMap
    status_transition_counts: CountMap
    context_coverage: dict[str, float | None]
    decision: str
    interpretation_limits: list[str]


class ResearchFindingsResponse(_ClosedContract):
    screening_holdout: ScreeningHoldoutFindingResponse
    context_validation: ContextValidationFindingResponse


class ResearchDataAccessResponse(_ClosedContract):
    provider: str
    access_url: str
    terms_url: str
    citation: str
    publication_notice_status: str
    publication_notice_date: str | None


class ResearchEvidenceResponse(_ClosedContract):
    schema_version: Literal["approach_aggregate_results_v1"]
    basis: Literal["real_opensky_research_data"]
    generated_at: str
    qualification: str
    allowed_role: str
    blocked_uses: list[str]
    limitations: list[str]
    cohorts: list[ResearchCohortResponse]
    findings: ResearchFindingsResponse
    data_access: ResearchDataAccessResponse
