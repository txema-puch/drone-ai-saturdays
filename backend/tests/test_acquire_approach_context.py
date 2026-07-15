import hashlib

from backend.scripts.acquire_approach_context import audit_sources


def test_source_audit_records_exact_weather_and_logical_aircraft_bytes(tmp_path) -> None:
    weather = tmp_path / "data/raw/weather"
    aircraft = tmp_path / "data/raw/aircraft_metadata"
    weather.mkdir(parents=True)
    aircraft.mkdir(parents=True)
    weather_bytes = b"weather-fixture"
    (weather / "lemd_isd_2025.csv").write_bytes(weather_bytes)
    (aircraft / "aircraftDatabase.part00").write_bytes(b"abc")
    (aircraft / "aircraftDatabase.part01").write_bytes(b"def")

    manifest = audit_sources(
        years=[2025],
        weather_dir=weather,
        aircraft_dir=aircraft,
        repository_root=tmp_path,
    )

    assert manifest["weather"]["files"][0]["sha256"] == hashlib.sha256(
        weather_bytes
    ).hexdigest()
    assert manifest["aircraft"]["logical_bytes"] == 6
    assert manifest["aircraft"]["logical_sha256"] == hashlib.sha256(b"abcdef").hexdigest()
    assert manifest["aircraft"]["license_scope"].startswith("non-profit research")
