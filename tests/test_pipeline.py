import pandas as pd
import pytest

from pipelinemedic.detection import CALIBRATION_END, TRAIN_END, checks, daily_history, detector
from pipelinemedic.pipeline import (
    BASE_SQL,
    SCENARIOS,
    apply_repair,
    fingerprint,
    load_lab,
    make_lab,
    reference_output,
    save_lab,
)
from pipelinemedic.service import evaluate


@pytest.mark.parametrize("scenario", list(SCENARIOS))
def test_all_fault_families_have_correct_output_or_abstain(scenario):
    lab = make_lab("2011-10-05", scenario, 73, 0.37)
    before = fingerprint(lab.raw)
    result, sandbox = evaluate(lab)
    assert fingerprint(lab.raw) == before, "Evaluation must not mutate input"
    if scenario in {"clean", "genuine_shift"}:
        assert result["status"] == "no_action"
        assert not result["patches"]
    else:
        assert result["verification"]["passed"], result
        assert fingerprint(sandbox.execute()) == fingerprint(reference_output(lab))


def test_duplicate_business_rows_and_returns_are_preserved(tiny_lab):
    tiny_lab.raw = pd.concat([tiny_lab.raw, tiny_lab.raw.iloc[[0]]], ignore_index=True)
    apply_repair(tiny_lab, "deduplicate_ingestion")
    out = tiny_lab.execute()
    assert len(out) == 4
    assert out.revenue.sum() == 6
    assert (out.quantity < 0).sum() == 1
    assert out.customer_id.isna().sum() == 2


def test_conflicting_duplicate_ids_are_not_arbitrarily_dropped(tiny_lab):
    extra = tiny_lab.raw.iloc[[0]].copy()
    extra["quantity"] = 999
    tiny_lab.raw = pd.concat([tiny_lab.raw, extra])
    with pytest.raises(ValueError, match="Conflicting"):
        apply_repair(tiny_lab, "deduplicate_ingestion")


def test_conflicting_dimensions_require_review(tiny_lab):
    extra = tiny_lab.dimension.iloc[[0]].copy()
    extra["product_description"] = "A conflicting description"
    tiny_lab.dimension = pd.concat([tiny_lab.dimension, extra])
    with pytest.raises(ValueError, match="Conflicting"):
        apply_repair(tiny_lab, "deduplicate_dimension")


def test_unknown_repair_is_rejected(tiny_lab):
    with pytest.raises(ValueError):
        apply_repair(tiny_lab, "DROP TABLE landing")


def test_fingerprint_is_order_independent_and_multiplicity_sensitive(tiny_lab):
    frame = tiny_lab.execute()
    assert fingerprint(frame) == fingerprint(frame.iloc[::-1])
    assert fingerprint(frame) != fingerprint(pd.concat([frame, frame.iloc[[0]]]))


def test_snapshot_roundtrip(tmp_path, tiny_lab):
    save_lab(tiny_lab, tmp_path / "snapshot")
    assert fingerprint(load_lab(tmp_path / "snapshot").execute()) == fingerprint(tiny_lab.execute())


def test_pipeline_error_is_reported_without_crashing(tiny_lab):
    tiny_lab.raw = tiny_lab.raw.rename(columns={"unit_price": "price_gbp"})
    result, _ = evaluate(tiny_lab)
    assert result["alert"]["execution_error"]
    assert result["verification"]["passed"]


def test_row_count_alone_does_not_validate_values(tiny_lab):
    tiny_lab.raw.loc[0, "unit_price"] = 999
    tests = checks(tiny_lab, tiny_lab.execute())
    assert next(t for t in tests if t["name"] == "Fact row conservation")["passed"]
    assert not next(t for t in tests if t["name"] == "Source value fidelity")["passed"]


def test_temporal_split_has_no_test_data():
    model, calibration, train = detector()
    assert train.date.max() <= TRAIN_END < CALIBRATION_END < "2011-09-01"
    assert len(calibration) == len(daily_history().query("date > @TRAIN_END and date <= @CALIBRATION_END"))


def test_missing_date_rejected():
    with pytest.raises(ValueError):
        make_lab("1900-01-01", "clean")


def test_unrecognized_transform_is_repaired_to_versioned_contract(tiny_lab):
    tiny_lab.sql = BASE_SQL + "\nWHERE r.customer_id IS NOT NULL"
    result, sandbox = evaluate(tiny_lab)
    assert result["investigation"]["diagnosis"]["roots"] == ["transform_regression"]
    assert fingerprint(sandbox.execute()) == fingerprint(reference_output(tiny_lab))
