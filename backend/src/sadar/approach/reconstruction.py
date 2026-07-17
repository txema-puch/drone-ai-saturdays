"""Temporal reconstruction of distinct final-corridor visits."""

from __future__ import annotations

import numpy as np
import pandas as pd

from sadar.approach.configuration import DEFAULT_CONFIG, ApproachConfig
from sadar.approach.geometry import GeometryCatalog, RunwayThreshold, load_lemd_geometry, runway_relative
from sadar.approach.inference import infer_runway
from sadar.approach.observations import canonical_observations


def _supported_gate_runs(
    frame: pd.DataFrame,
    runway: RunwayThreshold,
    config: ApproachConfig,
) -> list[tuple[int, int]]:
    """Return supported final-corridor visits, separating later re-approaches."""
    relative = runway_relative(frame["lat"], frame["lon"], runway)
    inside = (
        (relative.along_track_m >= -500.0)
        & (relative.along_track_m <= config.gate_along_m)
        & (np.abs(relative.cross_track_m) <= config.gate_cross_m)
    )
    indices = np.flatnonzero(inside)
    if not len(indices):
        return []
    time = frame["time"].to_numpy(dtype="int64")
    groups: list[list[int]] = [[int(indices[0])]]
    for index in indices[1:]:
        index = int(index)
        previous = groups[-1][-1]
        outside_rows = index - previous - 1
        outside_seconds = time[index] - time[previous]
        supported_exit = (
            outside_rows >= config.persistence_rows
            and outside_seconds >= config.persistence_s
        )
        if outside_seconds > config.attempt_reentry_gap_s or supported_exit:
            groups.append([index])
        else:
            groups[-1].append(index)
    return [
        (group[0], group[-1])
        for group in groups
        if len(group) >= config.inference_minimum_rows
    ]


def extract_approach_attempts(
    frame: pd.DataFrame,
    *,
    geometry: GeometryCatalog | None = None,
    config: ApproachConfig = DEFAULT_CONFIG,
) -> list[pd.DataFrame]:
    """Extract distinct observed final-corridor visits from one candidate record."""
    geometry = geometry or load_lemd_geometry()
    observations = canonical_observations(frame)
    if observations.empty:
        return []
    time = observations["time"].to_numpy(dtype="int64")
    supported_candidates: list[tuple[int, int]] = []
    for runway in geometry.landing_thresholds:
        for start, supported_end in _supported_gate_runs(
            observations, runway, config
        ):
            supported_candidates.append((start, supported_end))
    if not supported_candidates:
        return []

    supported_candidates.sort()
    clusters: list[list[tuple[int, int]]] = []
    for candidate in supported_candidates:
        if not clusters or candidate[0] > max(end for _, end in clusters[-1]):
            clusters.append([candidate])
        else:
            clusters[-1].append(candidate)

    attempts = []
    cluster_bounds = [
        (min(item[0] for item in cluster), max(item[1] for item in cluster))
        for cluster in clusters
    ]
    for cluster_index, (start, supported_end) in enumerate(cluster_bounds):
        extension_limit = time[supported_end] + config.outcome_extension_s
        end = int(np.searchsorted(time, extension_limit, side="right") - 1)
        if cluster_index + 1 < len(cluster_bounds):
            end = min(end, cluster_bounds[cluster_index + 1][0] - 1)
        end = max(supported_end, end)
        candidate = observations.iloc[start : end + 1].reset_index(drop=True)
        if infer_runway(
            candidate, geometry=geometry, config=config
        ).get("geometry_runway"):
            attempts.append(candidate)
    return attempts
