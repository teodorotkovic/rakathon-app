"""Import doplňkových vlastností (scénář 12)."""

from builders import EpisodeBuilder, build_bundle, cohort

from rakathon.features.extra import apply_meta, infer_meta, parse_extra, validate_extra, validate_meta
from rakathon.features.patient_table import reserved_columns
from rakathon.pipeline import compute_global


def _bundle(dxmap):
    eb = EpisodeBuilder()
    rows = cohort(10, "C91", 4, eb)
    return build_bundle(rows, eb.rows, [], dxmap)


def test_extra_feature_does_not_duplicate_patients_or_override_columns(dxmap, baseline_config):
    bundle = _bundle(dxmap)
    g0 = compute_global(bundle, baseline_config, dxmap)
    content = (
        b"patient_id,marker_x,sex,therapy_group,1bad\n"
        b"P0001,1.5,F,A,x\nP0002,,F,B,x\nP0003,abc,M,A,x\nP9999,2,M,A,x\n"
    )
    raw = parse_extra(content)
    clean, issues = validate_extra(raw, set(g0.core["patient_id"]), reserved_columns(g0.patient_table))
    codes = {i.code for i in issues}
    assert "reserved_name" in codes and "invalid_name" in codes and "unknown_patient" in codes
    assert list(clean.columns) == ["patient_id", "marker_x", "therapy_group"]
    meta = infer_meta(clean)
    assert dict(zip(meta["column"], meta["dtype"], strict=True)) == {
        "marker_x": "categorical",
        "therapy_group": "categorical",
    }
    meta.loc[meta["column"] == "marker_x", "dtype"] = "numeric"  # uživatel opraví odhad typu
    assert validate_meta(meta, clean) == []
    typed, conv = apply_meta(clean, meta)
    assert any(c.code == "not_numeric" for c in conv)

    bundle.extra, bundle.extra_meta = typed, meta
    g1 = compute_global(bundle, baseline_config, dxmap)
    assert len(g1.patient_table) == len(g0.patient_table) == 10
    t = g1.patient_table.set_index("patient_id")
    assert t.at["P0001", "marker_x"] == 1.5
    assert (t["sex"] == "M").all()  # základní sloupec nepřepsán
    # nová vlastnost se nedostane do očekávání: výsledky baseline beze změny
    assert g1.results_long[["patient_id", "metric_id", "expected", "reference_ids"]].equals(
        g0.results_long[["patient_id", "metric_id", "expected", "reference_ids"]]
    )
    assert g1.baseline_config_id == g0.baseline_config_id


def test_duplicate_keys_and_non_descriptor_roles_are_rejected(dxmap):
    bundle = _bundle(dxmap)
    raw = parse_extra(b"patient_id,marker\nP0001,1\nP0001,2\n")
    clean, issues = validate_extra(raw, set(bundle.patients["patient_id"]), set())
    assert clean is None and any(i.code == "duplicate_key" for i in issues)

    raw = parse_extra(b"patient_id,marker\nP0001,1\n")
    clean, _ = validate_extra(raw, set(bundle.patients["patient_id"]), set())
    meta = infer_meta(clean)
    meta["role"] = "baseline_input"
    assert any(i.code == "role" for i in validate_meta(meta, clean))
