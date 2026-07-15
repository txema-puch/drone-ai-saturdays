from __future__ import annotations

from pathlib import Path

import pytest

from backend.scripts import burn_approach_holdout as holdout


def test_burn_hashes_and_rejects_nonsealed_input_before_parquet_read(
    tmp_path: Path,
    monkeypatch,
):
    candidate = tmp_path / "candidate.parquet"
    candidate.write_bytes(b"not the sealed cohort")
    monkeypatch.setattr(
        holdout.pd,
        "read_parquet",
        lambda *_args, **_kwargs: (_ for _ in ()).throw(
            AssertionError("parquet must not be read")
        ),
    )
    with pytest.raises(ValueError, match="sealed digest"):
        holdout.burn(input_path=candidate)


def test_burn_contract_is_pinned_to_schema3_and_published_reference():
    assert holdout.SEALED_SHA256 == (
        "16f1bd2cbdbd519ce7bde6fbbc8df5012b188b54c5598bffc310cef34b0c6899"
    )
    assert holdout.DEFAULT_RELEASE.name == "sadar_approach_v3"
