"""Immutable release-derived indexes and per-application runtime state."""

from __future__ import annotations

from dataclasses import dataclass
from types import MappingProxyType
from typing import Any, Mapping

from sadar.api.middleware import EvaluationAdmissionLimiter

STATUS_PRIORITY = {
    "review_required": 0,
    "partial_observation": 1,
    "criteria_observed": 2,
    "not_assessable": 3,
}


@dataclass(frozen=True)
class ReleaseState:
    manifest: Mapping[str, Any]
    attempts: tuple[dict[str, Any], ...]
    attempts_by_id: Mapping[str, dict[str, Any]]
    ranked_attempts: tuple[dict[str, Any], ...]
    cases_by_id: Mapping[str, dict[str, Any]]
    operations_by_id: Mapping[str, dict[str, Any]]
    metrics: Mapping[str, Any]
    aggregate_results: Mapping[str, Any]
    reference: Mapping[str, Any]
    research: Mapping[str, Any] | None
    demo_data_origin: str
    release_id: str
    schema_version: int
    contextual: bool


@dataclass(frozen=True)
class RuntimeState:
    evaluation_slot: "EvaluationSlot"
    evaluation_limiter: EvaluationAdmissionLimiter


@dataclass
class EvaluationSlot:
    """Event-loop-local, non-queuing single-evaluation admission slot."""

    busy: bool = False

    def try_acquire(self) -> bool:
        if self.busy:
            return False
        self.busy = True
        return True

    def release(self) -> None:
        if not self.busy:
            raise RuntimeError("evaluation slot released while idle")
        self.busy = False


def build_release_state(release: Mapping[str, Any]) -> ReleaseState:
    attempts = tuple(release["attempts"])
    attempts_by_id = MappingProxyType(
        {item["attempt_id"]: item for item in attempts}
    )
    ranked = tuple(
        sorted(
            attempts,
            key=lambda item: (
                STATUS_PRIORITY.get(item["status"], 99),
                -int(item.get("start_time") or 0),
                item["attempt_id"],
            ),
        )
    )
    manifest = MappingProxyType(release["manifest"])
    return ReleaseState(
        manifest=manifest,
        attempts=attempts,
        attempts_by_id=attempts_by_id,
        ranked_attempts=ranked,
        cases_by_id=MappingProxyType(
            {item["case_id"]: item for item in release["cases"]}
        ),
        operations_by_id=MappingProxyType(
            {item["operation_id"]: item for item in release["operations"]}
        ),
        metrics=MappingProxyType(release["metrics"]),
        aggregate_results=MappingProxyType(release["aggregate_results"]),
        reference=MappingProxyType(release["reference"]),
        research=(
            MappingProxyType(release["research"])
            if release.get("research") is not None
            else None
        ),
        demo_data_origin=str(release["demo_data_origin"]),
        release_id=str(manifest["release_id"]),
        schema_version=int(manifest["schema_version"]),
        contextual=(
            manifest.get("contracts", {}).get("engine_version")
            == "approach_context_v1"
        ),
    )
