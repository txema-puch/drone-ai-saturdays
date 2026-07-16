"""Deterministic contextual-data adapters for approach screening.

The functions in this module deliberately keep source facts separate from derived
proxies.  NOAA Global Hourly values are decoded into canonical SI units, while
runway wind components and the QNH correction are explicitly labelled as
derivations rather than observations.
"""

from __future__ import annotations

import bisect
import csv
import io
import math
import re
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Iterable, Mapping, Sequence, TextIO


LEMD_GLOBAL_HOURLY_STATION = "08221099999"
STANDARD_PRESSURE_HPA = 1013.25
METRES_PER_HPA_PRESSURE_ALTITUDE_PROXY = 30.0 * 0.3048
DEFAULT_MAXIMUM_WEATHER_AGE_S = 1_800
_METAR_QNH_RE = re.compile(r"(?:^|\s)Q(\d{4})(?=\s|=|$)")
_NATURAL_PART_RE = re.compile(r"(\d+)")


@dataclass(frozen=True)
class WeatherObservation:
    """Canonical weather observation decoded from one Global Hourly row."""

    station: str
    observed_at: datetime
    report_type: str
    wind_from_direction_deg: float | None
    wind_speed_mps: float | None
    qnh_hpa: float | None
    raw_metar_qnh_hpa: float | None
    qnh_cross_check_delta_hpa: float | None
    qnh_cross_check_matches: bool | None
    temperature_c: float | None
    dew_point_c: float | None
    missing_reasons: tuple[str, ...]


@dataclass(frozen=True)
class WeatherJoin:
    """Result of a latest-prior weather join for an attempt midpoint."""

    attempt_midpoint: datetime
    observation: WeatherObservation | None
    nearest_observation_at: datetime | None
    age_seconds: float | None
    maximum_age_seconds: float
    missing_reasons: tuple[str, ...]


@dataclass(frozen=True)
class RunwayWindComponents:
    """Wind components relative to the aircraft's runway-aligned landing course.

    ``headwind_mps`` is positive for a headwind and negative for a tailwind.
    ``crosswind_from_right_mps`` is positive when the wind comes from the right
    side of the landing course and negative when it comes from the left.
    """

    headwind_mps: float
    crosswind_from_right_mps: float


@dataclass(frozen=True)
class QnhPressureAltitudeCorrectionProxy:
    """First-order ISA pressure correction, not geometric altitude.

    ``pressure_altitude_minus_qnh_altitude_proxy_m`` estimates how far pressure
    altitude referenced to 1013.25 hPa lies above QNH-referenced altitude.  Add
    ``qnh_altitude_from_pressure_altitude_addend_m`` to a pressure altitude to
    obtain the corresponding first-order QNH altitude proxy.
    """

    qnh_hpa: float
    pressure_altitude_minus_qnh_altitude_proxy_m: float
    qnh_altitude_from_pressure_altitude_addend_m: float


def _utc_datetime(value: datetime | str | int | float) -> datetime:
    if isinstance(value, datetime):
        parsed = value
    elif isinstance(value, (int, float)):
        parsed = datetime.fromtimestamp(value, tz=timezone.utc)
    else:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    if parsed.tzinfo is None:
        return parsed.replace(tzinfo=timezone.utc)
    return parsed.astimezone(timezone.utc)


def _valid_quality(flag: str) -> bool:
    # NCEI marks 2, 3, 6 and 7 as suspect/erroneous. Blank quality is not enough
    # evidence to reject an otherwise parseable value.
    return flag.strip() not in {"2", "3", "6", "7"}


def _signed_tenths(value: str, quality: str) -> float | None:
    if not value or value.lstrip("+-") == "9999" or not _valid_quality(quality):
        return None
    try:
        return int(value) / 10.0
    except ValueError:
        return None


def _parse_wnd(value: str | None) -> tuple[float | None, float | None]:
    fields = (value or "").split(",")
    if len(fields) < 5:
        return None, None
    direction_raw, direction_quality, _wind_type, speed_raw, speed_quality = fields[:5]
    direction: float | None = None
    speed: float | None = None
    if (
        direction_raw.isdigit()
        and direction_raw != "999"
        and 0 <= int(direction_raw) <= 360
        and _valid_quality(direction_quality)
    ):
        direction = float(int(direction_raw) % 360)
    if (
        speed_raw.isdigit()
        and speed_raw != "9999"
        and _valid_quality(speed_quality)
    ):
        speed = int(speed_raw) / 10.0
    return direction, speed


def _parse_ma1_qnh(value: str | None) -> float | None:
    fields = (value or "").split(",")
    if len(fields) < 2:
        return None
    raw, quality = fields[:2]
    if not raw.isdigit() or raw == "99999" or not _valid_quality(quality):
        return None
    qnh = int(raw) / 10.0
    return qnh if 850.0 <= qnh <= 1100.0 else None


def _parse_raw_metar_qnh(value: str | None) -> float | None:
    match = _METAR_QNH_RE.search(value or "")
    if match is None:
        return None
    qnh = float(match.group(1))
    return qnh if 850.0 <= qnh <= 1100.0 else None


def _decode_weather_row(row: Mapping[str, str]) -> WeatherObservation:
    wind_direction, wind_speed = _parse_wnd(row.get("WND", ""))
    qnh = _parse_ma1_qnh(row.get("MA1", ""))
    metar_qnh = _parse_raw_metar_qnh(row.get("REM", ""))
    qnh_delta = abs(qnh - metar_qnh) if qnh is not None and metar_qnh is not None else None
    qnh_matches = qnh_delta <= 0.6 if qnh_delta is not None else None
    missing = []
    if wind_direction is None:
        missing.append("wind_direction_missing_or_variable")
    if wind_speed is None:
        missing.append("wind_speed_missing")
    if qnh is None:
        missing.append("ma1_qnh_missing")
    if qnh is not None and metar_qnh is None:
        missing.append("raw_metar_qnh_cross_check_unavailable")
    elif qnh_matches is False:
        missing.append("ma1_raw_metar_qnh_mismatch")
        qnh = None
    temperature = _signed_tenths(*((row.get("TMP") or "").split(",", 1) + [""])[:2])
    dew_point = _signed_tenths(*((row.get("DEW") or "").split(",", 1) + [""])[:2])
    if temperature is None:
        missing.append("temperature_missing")
    if dew_point is None:
        missing.append("dew_point_missing")
    return WeatherObservation(
        station=row.get("STATION", "").strip(),
        observed_at=_utc_datetime(row["DATE"]),
        report_type=row.get("REPORT_TYPE", "").strip(),
        wind_from_direction_deg=wind_direction,
        wind_speed_mps=wind_speed,
        qnh_hpa=qnh,
        raw_metar_qnh_hpa=metar_qnh,
        qnh_cross_check_delta_hpa=qnh_delta,
        qnh_cross_check_matches=qnh_matches,
        temperature_c=temperature,
        dew_point_c=dew_point,
        missing_reasons=tuple(missing),
    )


def load_global_hourly_weather(
    source: str | Path | TextIO,
    *,
    station: str = LEMD_GLOBAL_HOURLY_STATION,
) -> list[WeatherObservation]:
    """Load station observations, preferring FM-15 METAR duplicates.

    Global Hourly commonly contains both SYNOP (FM-12) and METAR (FM-15) rows
    at the same timestamp.  Only one canonical row is retained per timestamp;
    FM-15 wins regardless of source-file row ordering.
    """

    should_close = not hasattr(source, "read")
    handle = open(source, encoding="utf-8-sig", newline="") if should_close else source
    try:
        selected: dict[datetime, WeatherObservation] = {}
        for row in csv.DictReader(handle):
            if row.get("STATION", "").strip() != station:
                continue
            observation = _decode_weather_row(row)
            current = selected.get(observation.observed_at)
            if current is None or (
                observation.report_type == "FM-15" and current.report_type != "FM-15"
            ):
                selected[observation.observed_at] = observation
        return [selected[key] for key in sorted(selected)]
    finally:
        if should_close:
            handle.close()


def join_latest_prior_weather(
    attempt_midpoint: datetime | str | int | float,
    observations: Sequence[WeatherObservation],
    *,
    maximum_age_seconds: float,
) -> WeatherJoin:
    """Join the latest prior observation without accepting future or stale context."""

    if maximum_age_seconds < 0:
        raise ValueError("maximum_age_seconds must be non-negative")
    midpoint = _utc_datetime(attempt_midpoint)
    ordered = sorted(observations, key=lambda item: item.observed_at)
    if not ordered:
        return WeatherJoin(
            attempt_midpoint=midpoint,
            observation=None,
            nearest_observation_at=None,
            age_seconds=None,
            maximum_age_seconds=float(maximum_age_seconds),
            missing_reasons=("weather_observation_unavailable",),
        )
    epochs = [item.observed_at.timestamp() for item in ordered]
    index = bisect.bisect_right(epochs, midpoint.timestamp()) - 1
    if index < 0:
        return WeatherJoin(
            attempt_midpoint=midpoint,
            observation=None,
            nearest_observation_at=ordered[0].observed_at,
            age_seconds=None,
            maximum_age_seconds=float(maximum_age_seconds),
            missing_reasons=("weather_observation_not_yet_available",),
        )
    nearest = ordered[index]
    age = (midpoint - nearest.observed_at).total_seconds()
    if age > maximum_age_seconds:
        return WeatherJoin(
            attempt_midpoint=midpoint,
            observation=None,
            nearest_observation_at=nearest.observed_at,
            age_seconds=age,
            maximum_age_seconds=float(maximum_age_seconds),
            missing_reasons=("latest_prior_weather_observation_too_old",),
        )
    return WeatherJoin(
        attempt_midpoint=midpoint,
        observation=nearest,
        nearest_observation_at=nearest.observed_at,
        age_seconds=age,
        maximum_age_seconds=float(maximum_age_seconds),
        missing_reasons=nearest.missing_reasons,
    )


# Compatibility alias for lifecycle artifacts and callers created before the
# latest-prior temporal contract was named explicitly.
join_nearest_weather = join_latest_prior_weather


def runway_relative_wind_components(
    *,
    wind_from_direction_deg: float,
    wind_speed_mps: float,
    runway_true_bearing_deg: float,
) -> RunwayWindComponents:
    """Resolve meteorological wind-FROM direction against runway bearing."""

    if not all(math.isfinite(value) for value in (
        wind_from_direction_deg, wind_speed_mps, runway_true_bearing_deg
    )):
        raise ValueError("wind direction, speed and runway bearing must be finite")
    if wind_speed_mps < 0:
        raise ValueError("wind_speed_mps must be non-negative")
    angle = math.radians((wind_from_direction_deg - runway_true_bearing_deg) % 360.0)
    return RunwayWindComponents(
        headwind_mps=wind_speed_mps * math.cos(angle),
        crosswind_from_right_mps=wind_speed_mps * math.sin(angle),
    )


def qnh_pressure_altitude_correction_proxy(
    qnh_hpa: float,
) -> QnhPressureAltitudeCorrectionProxy:
    """Return the first-order 30 ft/hPa QNH pressure-altitude proxy."""

    if not math.isfinite(qnh_hpa) or not 850.0 <= qnh_hpa <= 1100.0:
        raise ValueError("qnh_hpa must be a plausible finite pressure")
    pressure_minus_qnh = (STANDARD_PRESSURE_HPA - qnh_hpa) * (
        METRES_PER_HPA_PRESSURE_ALTITUDE_PROXY
    )
    return QnhPressureAltitudeCorrectionProxy(
        qnh_hpa=qnh_hpa,
        pressure_altitude_minus_qnh_altitude_proxy_m=pressure_minus_qnh,
        qnh_altitude_from_pressure_altitude_addend_m=-pressure_minus_qnh,
    )


class _ConcatenatedBinaryParts(io.RawIOBase):
    """Read byte-range parts as one stream without creating a joined file."""

    def __init__(self, paths: Sequence[Path]) -> None:
        super().__init__()
        self._paths = iter(paths)
        self._current: io.BufferedReader | None = None

    def readable(self) -> bool:
        return True

    def readinto(self, buffer: bytearray) -> int:
        view = memoryview(buffer)
        written = 0
        while written < len(view):
            if self._current is None:
                try:
                    self._current = open(next(self._paths), "rb")
                except StopIteration:
                    break
            count = self._current.readinto(view[written:])
            if count:
                written += count
            else:
                self._current.close()
                self._current = None
        return written

    def close(self) -> None:
        if self._current is not None:
            self._current.close()
            self._current = None
        super().close()


def _natural_part_key(path: Path) -> tuple[object, ...]:
    return tuple(
        int(token) if token.isdigit() else token
        for token in _NATURAL_PART_RE.split(path.name)
    )


def load_aircraft_metadata_parts(
    parts_directory: str | Path,
    requested_icao24: Iterable[str],
    *,
    pattern: str = "aircraftDatabase.part*",
) -> dict[str, dict[str, str]]:
    """Return requested OpenSky aircraft rows from raw byte-range CSV parts.

    Parts are streamed as a single logical byte sequence.  This is important:
    range boundaries may split quoted CSV records, embedded newlines, or even a
    multi-byte UTF-8 character.  The function never materializes a concatenated
    file and stops once every requested ICAO24 has been found.
    """

    requested = {value.strip().lower() for value in requested_icao24 if value.strip()}
    if not requested:
        return {}
    paths = sorted(Path(parts_directory).glob(pattern), key=_natural_part_key)
    if not paths:
        raise FileNotFoundError(f"no aircraft metadata parts matched {pattern!r}")
    raw = _ConcatenatedBinaryParts(paths)
    buffered = io.BufferedReader(raw)
    text = io.TextIOWrapper(buffered, encoding="utf-8-sig", newline="")
    found: dict[str, dict[str, str]] = {}
    try:
        for row in csv.DictReader(text):
            icao24 = (row.get("icao24") or "").strip().lower()
            if icao24 in requested and icao24 not in found:
                found[icao24] = dict(row)
                if len(found) == len(requested):
                    break
    finally:
        text.close()
    return found
