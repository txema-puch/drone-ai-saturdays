"""Declarative synthetic approach scenarios.

The profiles below are mathematical control points over normalized scenario time.
They are pedagogical inputs, not copied, sampled, or perturbed source trajectories.
"""

from __future__ import annotations

from dataclasses import dataclass


Profile = tuple[tuple[float, float], ...]
ProfileSpec = Profile | str
CoverageGaps = tuple[tuple[int, int], ...]


@dataclass(frozen=True)
class Scenario:
    scenario_id: str
    title: str
    teaching_goal: str
    runway: str
    start_along_track_m: float
    end_along_track_m: float
    duration_s: int
    sample_interval_s: int
    cross_track_profile_m: Profile
    barometric_altitude_profile_m: ProfileSpec
    ground_speed_profile_mps: Profile
    vertical_rate_profile_mps: Profile
    heading_offset_profile_deg: Profile
    coverage_gaps: CoverageGaps
    expected_status: str
    expected_failed_criteria: tuple[str, ...]
    expected_outcome: str
    expected_runway_specificity: str
    expected_quality_flags: tuple[str, ...]


def _flat(value: float) -> Profile:
    return ((0.0, value), (1.0, value))


THREE_DEGREE: ProfileSpec = "three_degree"
STABLE_SPEED: Profile = ((0.0, 85.0), (0.35, 79.0), (0.70, 72.0), (1.0, 68.0))
STABLE_RATE: Profile = _flat(-3.0)
STRAIGHT: Profile = _flat(0.0)
CENTERLINE: Profile = _flat(0.0)


SCENARIOS: tuple[Scenario, ...] = (
    Scenario(
        "stable-rwy-32l", "Stable RWY 32L approach",
        "Shows all observable criteria within their synthetic reference envelopes.",
        "32L", 12_000.0, 100.0, 240, 2, CENTERLINE, THREE_DEGREE,
        STABLE_SPEED, STABLE_RATE, STRAIGHT, (), "criteria_observed", (),
        "landing_observed", "exact", (),
    ),
    Scenario(
        "low-speed-rwy-32l", "Lower-than-reference speed",
        "Explains a persistent lower-bound ground-speed review signal.",
        "32L", 12_000.0, 100.0, 240, 2, CENTERLINE, THREE_DEGREE,
        _flat(55.0), STABLE_RATE, STRAIGHT, (), "review_required",
        ("observed_ground_speed_envelope",), "final_gate_observed", "exact", (),
    ),
    Scenario(
        "high-speed-rwy-18r", "Higher-than-reference speed",
        "Explains a persistent upper-bound ground-speed review signal.",
        "18R", 12_000.0, 100.0, 240, 2, CENTERLINE, THREE_DEGREE,
        _flat(130.0), STABLE_RATE, STRAIGHT, (), "review_required",
        ("observed_ground_speed_envelope",), "final_gate_observed", "exact", (),
    ),
    Scenario(
        "descent-rate-rwy-32r", "High observed descent rate",
        "Explains a persistent observed descent-rate review signal.",
        "32R", 12_000.0, 100.0, 240, 2, CENTERLINE, THREE_DEGREE,
        STABLE_SPEED, _flat(-10.0), STRAIGHT, (), "review_required",
        ("observed_descent_rate",), "final_gate_observed", "exact", (),
    ),
    Scenario(
        "lateral-offset-rwy-18l", "Lateral corridor offset",
        "Explains a persistent lateral-path proxy review signal.",
        "18L", 12_000.0, 100.0, 240, 2, _flat(-500.0), THREE_DEGREE,
        STABLE_SPEED, STABLE_RATE, STRAIGHT, (), "review_required",
        ("lateral_path_proxy",), "final_gate_observed", "exact", (),
    ),
    Scenario(
        "late-track-correction-rwy-32l", "Late track correction",
        "Explains a sustained heading correction inside the final 3 km proxy gate.",
        "32L", 12_000.0, 100.0, 240, 2, CENTERLINE, THREE_DEGREE,
        STABLE_SPEED, STABLE_RATE, ((0.0, 0.0), (0.70, 0.0), (0.72, 25.0), (1.0, 25.0)),
        (), "review_required", ("late_track_correction",),
        "final_gate_observed", "exact", (),
    ),
    Scenario(
        "multi-criterion-rwy-18r", "Multiple review signals",
        "Shows that independent persistent criteria remain separately inspectable.",
        "18R", 12_000.0, 100.0, 240, 2, CENTERLINE, THREE_DEGREE,
        _flat(130.0), _flat(-10.0), STRAIGHT, (), "review_required",
        ("observed_descent_rate", "observed_ground_speed_envelope"),
        "final_gate_observed", "exact", (),
    ),
    Scenario(
        "evidence-ends-early-rwy-32l", "Evidence ends before the runway",
        "Separates entry into the analysis gate from availability of a landing outcome.",
        "32L", 12_000.0, 3_500.0, 240, 2, CENTERLINE, THREE_DEGREE,
        STABLE_SPEED, STABLE_RATE, STRAIGHT, (), "partial_observation", (),
        "final_gate_observed", "exact", (),
    ),
    Scenario(
        "short-record-rwy-18l", "Short observation record",
        "Shows abstention when duration and row coverage are insufficient.",
        "18L", 12_000.0, 7_000.0, 70, 10, CENTERLINE, THREE_DEGREE,
        STABLE_SPEED, STABLE_RATE, STRAIGHT, (), "not_assessable", (),
        "incomplete", "exact",
        ("insufficient_observations", "insufficient_duration", "terminal_gate_not_reached"),
    ),
    Scenario(
        "large-internal-gap-rwy-32r", "Large internal evidence gap",
        "Shows abstention when observed positions contain a material time gap.",
        "32R", 12_000.0, 100.0, 240, 2, CENTERLINE, THREE_DEGREE,
        STABLE_SPEED, STABLE_RATE, STRAIGHT, ((90, 160),), "not_assessable", (),
        "final_gate_observed", "exact", ("approach_coverage_gap",),
    ),
    Scenario(
        "parallel-runway-ambiguity-32", "Parallel RWY 32 ambiguity",
        "Shows direction-level inference when geometry cannot separate a parallel runway.",
        "32L", 12_000.0, 100.0, 240, 2, _flat(900.0), THREE_DEGREE,
        STABLE_SPEED, STABLE_RATE, STRAIGHT, (), "review_required",
        ("lateral_path_proxy",), "final_gate_observed", "direction", (),
    ),
    Scenario(
        "go-around-rwy-18r", "Observed go-around pattern",
        "Shows a descent-then-climb proxy without claiming a certified outcome.",
        "18R", 12_000.0, 800.0, 300, 2, CENTERLINE,
        ((0.0, 700.0), (0.70, 120.0), (1.0, 520.0)), STABLE_SPEED,
        STABLE_RATE, STRAIGHT, (), "partial_observation", (),
        "go_around", "exact", (),
    ),
    Scenario(
        "touch-and-go-rwy-32l", "Observed touch-and-go pattern",
        "Shows ground contact followed by climb as an observed proxy pattern.",
        "32L", 12_000.0, -200.0, 300, 2, CENTERLINE,
        ((0.0, 700.0), (0.85, 0.0), (1.0, 350.0)), STABLE_SPEED,
        STABLE_RATE, STRAIGHT, (), "partial_observation", (),
        "touch_and_go", "exact", (),
    ),
    Scenario(
        "altitude-rate-conflict-rwy-32l", "Altitude-rate conflict",
        "Shows a barometric advisory while other observable criteria remain usable.",
        "32L", 12_000.0, 100.0, 240, 2, CENTERLINE,
        ((0.0, -1.0), (0.48, -1.0), (0.50, 1_000.0), (0.52, -1.0), (1.0, -1.0)),
        STABLE_SPEED, STABLE_RATE, STRAIGHT, (), "partial_observation", (),
        "final_gate_observed", "exact", ("altitude_rate_conflict",),
    ),
)


SCENARIO_IDS = frozenset(item.scenario_id for item in SCENARIOS)
