import pytest

from sadar.pipelines import evaluate_context as evaluation


def test_contextual_comparison_rejects_train_and_burned_test_roles() -> None:
    for cohort in ("train", "test", "2026"):
        with pytest.raises(ValueError, match="restricted to val or 2025"):
            evaluation.evaluate(cohort=cohort)
