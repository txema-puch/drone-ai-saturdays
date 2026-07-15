import hashlib

import pytest

from backend.scripts import audit_approach_dataset as audit


def test_dataset_audit_refuses_a_sealed_hash_before_reading(tmp_path, monkeypatch):
    path = tmp_path / "sealed.parquet"
    path.write_bytes(b"sealed fixture")
    digest = hashlib.sha256(path.read_bytes()).hexdigest()
    monkeypatch.setattr(audit, "SEALED_HOLDOUT_SHA256", {digest})
    monkeypatch.setattr(
        audit.pd,
        "read_parquet",
        lambda _path: pytest.fail("sealed data must not be read"),
    )
    with pytest.raises(ValueError, match="sealed 2026 holdout"):
        audit.audit_dataset(path, reference={})
