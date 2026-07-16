from __future__ import annotations

from pathlib import Path

import pytest

from sadar.pipelines import audit_context as audit


def test_context_audit_rejects_unknown_cohort() -> None:
    with pytest.raises(ValueError, match="train, val, or 2025"):
        audit.audit_context(cohort="test")


def test_context_audit_refuses_burned_holdout_before_read(
    tmp_path: Path,
    monkeypatch,
) -> None:
    source = tmp_path / "holdout.parquet"
    source.write_bytes(b"sealed")
    monkeypatch.setattr(audit, "file_sha256", lambda _path: next(iter(audit.SEALED_HOLDOUT_SHA256)))
    monkeypatch.setattr(
        audit.pd,
        "read_parquet",
        lambda *_args, **_kwargs: (_ for _ in ()).throw(
            AssertionError("burned holdout must not be read")
        ),
    )

    with pytest.raises(ValueError, match="burned 2026 holdout"):
        audit._load_frame("2025", tmp_path, source)


def test_logical_parts_digest_matches_concatenated_bytes(tmp_path: Path) -> None:
    (tmp_path / "aircraftDatabase.part00").write_bytes(b"abc")
    (tmp_path / "aircraftDatabase.part01").write_bytes(b"def")

    assert audit._logical_parts_sha256(tmp_path) == (
        "bef57ec7f53a6d40beb640a780a639c83bc29ac8a9816f1fc6c5c6dcd93c4721"
    )
