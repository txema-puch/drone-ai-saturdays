from sadar.approach.reference import (
    load_context_reference,
    lookup_reference,
    validate_reference,
)


def test_published_contextual_reference_is_typed_with_unknown_fallback() -> None:
    reference = load_context_reference()
    validate_reference(reference)
    assert reference["fit_fold"] == "train"
    assert reference["quantile_weighting"] == "equal_attempt_empirical_cdf_v1"
    assert max(item["speed_upper_mps"] for item in reference["entries"]) <= 150.0
    assert reference["stratification"]["fleet"]["status"] == (
        "typecode_conditioned_with_unknown_fallback"
    )
    exact_entry = next(
        item for item in reference["entries"] if item["speed_class"] != "unknown"
    )
    lower = float(exact_entry["distance_bin_m"].split("-")[0])
    match = lookup_reference(
        reference,
        direction=exact_entry["direction"],
        speed_class=exact_entry["speed_class"],
        along_track_m=lower + 1,
    )
    fallback = lookup_reference(
        reference,
        direction=exact_entry["direction"],
        speed_class="UNSEEN",
        along_track_m=lower + 1,
    )
    assert match is not None and match["fallback"] == "exact"
    assert fallback is not None and fallback["fallback"] == "unknown_speed_class"
