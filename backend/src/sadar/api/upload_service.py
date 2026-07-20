"""Bounded, ephemeral rules-first evaluation of uploaded approach observations.

This module intentionally does not import the historical upload evaluator: that
module imports the Torch scoring stack at import time.  The parser and canonical
normalizer below preserve its public error contract while keeping approach
screening independent from model preparation and resampling.
"""

from __future__ import annotations

import hashlib
from pathlib import PurePath
from typing import Any

from sadar.approach.assessment import assess_approach, extract_approach_attempts
from sadar.approach.reference import load_approach_reference, validate_reference
from sadar.approach.contextual import assess_contextual_operation
from sadar.trajectory.segmentation import add_flight_id
from sadar.releases.approach import canonical_json_bytes
from sadar.api.upload_contract import (
    CONTEXT_COLUMNS,
    MAX_ATTEMPTS,
    MAX_INPUT_BYTES,
    MAX_OPERATIONS,
    MAX_RESPONSE_BYTES,
    SCHEMA_VERSION,
    EvaluationError,
    field_error as _field,
)
from sadar.api.upload_context import supplied_context as _supplied_context
from sadar.api.upload_normalization import normalize_upload as _normalize
from sadar.api.upload_parsing import parse_upload as _parse
from sadar.api.upload_presentation import evaluation_result as _result


class ApproachUploadEvaluationService:
    """Evaluate raw OpenSky observations with the published approach contract."""

    def __init__(
        self,
        *,
        release_id: str,
        reference: dict[str, Any] | None = None,
        contextual: bool = False,
    ) -> None:
        if not release_id:
            raise ValueError("release_id is required")
        self.release_id = release_id
        self.reference = reference if reference is not None else load_approach_reference()
        self.contextual = contextual
        validate_reference(self.reference)

    def evaluate(
        self,
        data: bytes,
        *,
        filename: str,
        media_type: str,
    ) -> dict[str, Any]:
        if not data:
            raise EvaluationError(422, "empty_file", "The file contains no observations.")
        if len(data) > MAX_INPUT_BYTES:
            raise EvaluationError(
                413, "request_too_large", "The upload exceeds the 10 MiB limit."
            )
        suffix = PurePath(filename or "").suffix.lower()
        upload_sha256 = hashlib.sha256(data).hexdigest()
        raw = _parse(data, suffix=suffix, media_type=media_type)
        raw_rows = int(len(raw))
        normalized, duplicate_rows, dataset_digest = _normalize(raw)
        if not self.contextual and normalized[list(CONTEXT_COLUMNS)].notna().any().any():
            raise EvaluationError(
                422,
                "context_not_supported",
                "The loaded release does not support contextual upload fields.",
                tuple(
                    _field(
                        field,
                        "Remove this field or use a contextual release.",
                        "unsupported_for_release",
                    )
                    for field in CONTEXT_COLUMNS
                    if normalized[field].notna().any()
                ),
            )
        operations_frame = add_flight_id(normalized)
        operation_groups = list(operations_frame.groupby("flight_id", sort=True))
        if len(operation_groups) > MAX_OPERATIONS:
            raise EvaluationError(
                413, "too_many_operations",
                f"At most {MAX_OPERATIONS} candidate operations are accepted.",
            )

        results: list[dict[str, Any]] = []
        rejection_reasons: list[dict[str, Any]] = []
        for operation_id, operation in operation_groups:
            attempt_frames = extract_approach_attempts(operation)
            if not attempt_frames:
                rejection_reasons.append({
                    "code": "no_supported_approach_attempt",
                    "message": (
                        "The operation did not contain a supported LEMD final-corridor visit; "
                        "no holding, diversion, or intent label was inferred."
                    ),
                    "count": 1,
                    "operation_id": str(operation_id),
                })
            if len(results) + len(attempt_frames) > MAX_ATTEMPTS:
                raise EvaluationError(
                    413, "too_many_attempts",
                    f"At most {MAX_ATTEMPTS} approach attempts are accepted.",
                )
            if self.contextual:
                weather, aircraft_metadata = _supplied_context(operation)
                contextual = assess_contextual_operation(
                    operation,
                    operation_id=str(operation_id),
                    weather=weather,
                    aircraft_metadata=aircraft_metadata,
                    reference=self.reference,
                )
                assessments = contextual["attempts"]
                if len(assessments) != len(attempt_frames):
                    raise RuntimeError("Contextual attempt extraction diverged from upload extraction.")
            else:
                assessments = [
                    assess_approach(
                        attempt_frame,
                        operation_id=f"{operation_id}:attempt-{attempt_index}",
                        reference=self.reference,
                    )
                    for attempt_index, attempt_frame in enumerate(attempt_frames, start=1)
                ]
            for attempt_index, (attempt_frame, assessment) in enumerate(
                zip(attempt_frames, assessments, strict=True), start=1,
            ):
                results.append(_result(
                    assessment=assessment,
                    attempt_frame=attempt_frame,
                    dataset_digest=dataset_digest,
                    operation_id=str(operation_id),
                    attempt_index=attempt_index,
                ))

        status_counts: dict[str, int] = {}
        for result in results:
            status = str(result["status"])
            status_counts[status] = status_counts.get(status, 0) + 1
        response = {
            "schema_version": SCHEMA_VERSION,
            "data_origin": "user_upload_ephemeral",
            "reference_origin": "derived_from_aggregate_real_research",
            "release_id": self.release_id,
            "reference_sha256": self.reference["artifact_sha256"],
            "dataset_digest": dataset_digest,
            "upload_sha256": upload_sha256,
            "raw_rows": raw_rows,
            "canonical_rows": int(len(normalized)),
            "duplicate_rows_collapsed": duplicate_rows,
            "operations": len(operation_groups),
            "attempts": len(results),
            "status_counts": dict(sorted(status_counts.items())),
            "rejection_reasons": rejection_reasons,
            "results": results,
        }
        if len(canonical_json_bytes(response)) > MAX_RESPONSE_BYTES:
            raise EvaluationError(
                413, "evaluation_response_too_large",
                "The bounded evaluation result exceeds the response limit.",
            )
        return response
