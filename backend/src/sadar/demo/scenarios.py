"""Declarative synthetic approach scenarios.

The profiles below are mathematical control points over normalized scenario time.
They are pedagogical inputs, not copied, sampled, or perturbed source trajectories.
"""

from __future__ import annotations

from dataclasses import dataclass


Profile = tuple[tuple[float, float], ...]
ProfileSpec = Profile | str
CoverageGaps = tuple[tuple[int, int], ...]
GroundContactWindowsM = tuple[tuple[float, float], ...]


@dataclass(frozen=True, kw_only=True)
class Scenario:
    scenario_id: str
    title: str
    teaching_goal: str
    runway: str
    end_along_track_m: float
    duration_s: int
    sample_interval_s: int
    cross_track_profile_m: Profile
    barometric_altitude_profile_m: ProfileSpec
    ground_speed_profile_mps: Profile
    coverage_gaps: CoverageGaps
    expected_status: str
    expected_failed_criteria: tuple[str, ...]
    expected_outcome: str
    expected_runway_specificity: str
    expected_quality_flags: tuple[str, ...]
    ground_contact_along_windows_m: GroundContactWindowsM = ()
    vertical_rate_override_profile_mps: Profile | None = None


def _flat(value: float) -> Profile:
    return ((0.0, value), (1.0, value))


THREE_DEGREE: ProfileSpec = "three_degree"
TOUCH_AND_GO: ProfileSpec = "touch_and_go"
STEEP_FINAL: ProfileSpec = "steep_final"
STABLE_SPEED: Profile = _flat(78.0)
STABLE_RATE: Profile = _flat(-2.6)
NOMINAL_INTERCEPT: Profile = (
    (0.0, 320.0),
    (0.20, 220.0),
    (0.45, 75.0),
    (0.65, 25.0),
    (0.82, 5.0),
    (1.0, 0.0),
)
LATE_CORRECTION: Profile = (
    (0.0, 500.0),
    (0.90, 500.0),
    (1.0, 0.0),
)


SCENARIOS: tuple[Scenario, ...] = (
    Scenario(
        scenario_id="stable-rwy-32l",
        title="Stable RWY 32L approach",
        teaching_goal="Shows all observable criteria within their synthetic reference envelopes.",
        runway="32L",
        end_along_track_m=-500.0,
        duration_s=240,
        sample_interval_s=2,
        cross_track_profile_m=NOMINAL_INTERCEPT,
        barometric_altitude_profile_m=THREE_DEGREE,
        ground_speed_profile_mps=STABLE_SPEED,
        coverage_gaps=(),
        expected_status="criteria_observed",
        expected_failed_criteria=(),
        expected_outcome="landing_observed",
        expected_runway_specificity="exact",
        expected_quality_flags=(),
        ground_contact_along_windows_m=((50.0, -500.0),),
    ),
    Scenario(
        scenario_id="low-speed-rwy-32l",
        title="Lower-than-reference speed",
        teaching_goal="Explains a persistent lower-bound ground-speed review signal.",
        runway="32L", end_along_track_m=100.0, duration_s=240, sample_interval_s=2,
        cross_track_profile_m=NOMINAL_INTERCEPT,
        barometric_altitude_profile_m=THREE_DEGREE,
        ground_speed_profile_mps=_flat(55.0), coverage_gaps=(),
        expected_status="review_required",
        expected_failed_criteria=("observed_ground_speed_envelope",),
        expected_outcome="final_gate_observed", expected_runway_specificity="exact",
        expected_quality_flags=(),
    ),
    Scenario(
        scenario_id="high-speed-rwy-18r", title="Higher-than-reference speed",
        teaching_goal="Explains a persistent upper-bound ground-speed review signal.",
        runway="18R", end_along_track_m=100.0, duration_s=240, sample_interval_s=2,
        cross_track_profile_m=NOMINAL_INTERCEPT,
        barometric_altitude_profile_m=THREE_DEGREE,
        ground_speed_profile_mps=_flat(90.0), coverage_gaps=(),
        expected_status="review_required",
        expected_failed_criteria=("observed_ground_speed_envelope",),
        expected_outcome="final_gate_observed", expected_runway_specificity="exact",
        expected_quality_flags=(),
    ),
    Scenario(
        scenario_id="descent-rate-rwy-32r", title="High observed descent rate",
        teaching_goal="Explains a persistent observed descent-rate review signal.",
        runway="32R", end_along_track_m=100.0, duration_s=240, sample_interval_s=2,
        cross_track_profile_m=NOMINAL_INTERCEPT,
        barometric_altitude_profile_m=STEEP_FINAL,
        ground_speed_profile_mps=STABLE_SPEED, coverage_gaps=(),
        expected_status="review_required", expected_failed_criteria=("observed_descent_rate",),
        expected_outcome="final_gate_observed", expected_runway_specificity="exact",
        expected_quality_flags=(),
    ),
    Scenario(
        scenario_id="lateral-offset-rwy-18l", title="Lateral corridor offset",
        teaching_goal="Explains a persistent lateral-path proxy review signal.",
        runway="18L", end_along_track_m=100.0, duration_s=240, sample_interval_s=2,
        cross_track_profile_m=_flat(-500.0), barometric_altitude_profile_m=THREE_DEGREE,
        ground_speed_profile_mps=STABLE_SPEED, coverage_gaps=(),
        expected_status="review_required", expected_failed_criteria=("lateral_path_proxy",),
        expected_outcome="final_gate_observed", expected_runway_specificity="exact",
        expected_quality_flags=(),
    ),
    Scenario(
        scenario_id="late-track-correction-rwy-32l", title="Late track correction",
        teaching_goal="Explains a sustained heading correction inside the final 3 km proxy gate.",
        runway="32L", end_along_track_m=100.0, duration_s=240, sample_interval_s=2,
        cross_track_profile_m=LATE_CORRECTION, barometric_altitude_profile_m=THREE_DEGREE,
        ground_speed_profile_mps=STABLE_SPEED, coverage_gaps=(),
        expected_status="review_required",
        expected_failed_criteria=("lateral_path_proxy", "late_track_correction"),
        expected_outcome="final_gate_observed", expected_runway_specificity="exact",
        expected_quality_flags=(),
    ),
    Scenario(
        scenario_id="multi-criterion-rwy-18r", title="Multiple review signals",
        teaching_goal="Shows that independent persistent criteria remain separately inspectable.",
        runway="18R", end_along_track_m=100.0, duration_s=240, sample_interval_s=2,
        cross_track_profile_m=NOMINAL_INTERCEPT, barometric_altitude_profile_m=STEEP_FINAL,
        ground_speed_profile_mps=_flat(90.0), coverage_gaps=(),
        expected_status="review_required",
        expected_failed_criteria=("observed_descent_rate", "observed_ground_speed_envelope"),
        expected_outcome="final_gate_observed", expected_runway_specificity="exact",
        expected_quality_flags=(),
    ),
    Scenario(
        scenario_id="evidence-ends-early-rwy-32l", title="Evidence ends before the runway",
        teaching_goal="Separates entry into the analysis gate from availability of a landing outcome.",
        runway="32L", end_along_track_m=3_500.0, duration_s=240, sample_interval_s=2,
        cross_track_profile_m=NOMINAL_INTERCEPT, barometric_altitude_profile_m=THREE_DEGREE,
        ground_speed_profile_mps=STABLE_SPEED, coverage_gaps=(),
        expected_status="partial_observation", expected_failed_criteria=(),
        expected_outcome="final_gate_observed", expected_runway_specificity="exact",
        expected_quality_flags=(),
    ),
    Scenario(
        scenario_id="short-record-rwy-18l", title="Short observation record",
        teaching_goal="Shows abstention when duration and row coverage are insufficient.",
        runway="18L", end_along_track_m=7_000.0, duration_s=70, sample_interval_s=10,
        cross_track_profile_m=NOMINAL_INTERCEPT, barometric_altitude_profile_m=THREE_DEGREE,
        ground_speed_profile_mps=STABLE_SPEED, coverage_gaps=(),
        expected_status="not_assessable", expected_failed_criteria=(),
        expected_outcome="incomplete", expected_runway_specificity="exact",
        expected_quality_flags=("insufficient_observations", "insufficient_duration", "terminal_gate_not_reached"),
    ),
    Scenario(
        scenario_id="large-internal-gap-rwy-32r", title="Large internal evidence gap",
        teaching_goal="Shows abstention when observed positions contain a material time gap.",
        runway="32R", end_along_track_m=100.0, duration_s=240, sample_interval_s=2,
        cross_track_profile_m=NOMINAL_INTERCEPT, barometric_altitude_profile_m=THREE_DEGREE,
        ground_speed_profile_mps=STABLE_SPEED, coverage_gaps=((90, 160),),
        expected_status="not_assessable", expected_failed_criteria=(),
        expected_outcome="final_gate_observed", expected_runway_specificity="exact",
        expected_quality_flags=("approach_coverage_gap",),
    ),
    Scenario(
        scenario_id="parallel-runway-ambiguity-32", title="Parallel RWY 32 ambiguity",
        teaching_goal="Shows direction-level inference when geometry cannot separate a parallel runway.",
        runway="32L", end_along_track_m=100.0, duration_s=240, sample_interval_s=2,
        cross_track_profile_m=_flat(900.0), barometric_altitude_profile_m=THREE_DEGREE,
        ground_speed_profile_mps=STABLE_SPEED, coverage_gaps=(),
        expected_status="review_required", expected_failed_criteria=("lateral_path_proxy",),
        expected_outcome="final_gate_observed", expected_runway_specificity="direction",
        expected_quality_flags=(),
    ),
    Scenario(
        scenario_id="go-around-rwy-18r", title="Observed go-around pattern",
        teaching_goal="Shows a descent-then-climb proxy without claiming a certified outcome.",
        runway="18R", end_along_track_m=800.0, duration_s=300, sample_interval_s=2,
        cross_track_profile_m=NOMINAL_INTERCEPT,
        barometric_altitude_profile_m=((0.0, 700.0), (0.70, 120.0), (1.0, 520.0)),
        ground_speed_profile_mps=STABLE_SPEED, coverage_gaps=(),
        expected_status="partial_observation", expected_failed_criteria=(),
        expected_outcome="go_around", expected_runway_specificity="exact",
        expected_quality_flags=(),
    ),
    Scenario(
        scenario_id="touch-and-go-rwy-32l", title="Observed touch-and-go pattern",
        teaching_goal="Shows ground contact followed by climb as an observed proxy pattern.",
        runway="32L", end_along_track_m=-3_000.0, duration_s=300, sample_interval_s=2,
        cross_track_profile_m=NOMINAL_INTERCEPT, barometric_altitude_profile_m=TOUCH_AND_GO,
        ground_speed_profile_mps=STABLE_SPEED, coverage_gaps=(),
        expected_status="criteria_observed", expected_failed_criteria=(),
        expected_outcome="touch_and_go", expected_runway_specificity="exact",
        expected_quality_flags=(), ground_contact_along_windows_m=((50.0, -50.0),),
    ),
    Scenario(
        scenario_id="altitude-rate-conflict-rwy-32l", title="Altitude-rate conflict",
        teaching_goal="Shows a barometric advisory while other observable criteria remain usable.",
        runway="32L", end_along_track_m=100.0, duration_s=240, sample_interval_s=2,
        cross_track_profile_m=NOMINAL_INTERCEPT,
        barometric_altitude_profile_m=((0.0, -1.0), (0.48, -1.0), (0.50, 1_000.0), (0.52, -1.0), (1.0, -1.0)),
        ground_speed_profile_mps=STABLE_SPEED, coverage_gaps=(),
        expected_status="partial_observation", expected_failed_criteria=(),
        expected_outcome="final_gate_observed", expected_runway_specificity="exact",
        expected_quality_flags=("altitude_rate_conflict",),
        vertical_rate_override_profile_mps=STABLE_RATE,
    ),
)


SCENARIO_IDS = frozenset(item.scenario_id for item in SCENARIOS)
