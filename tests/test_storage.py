"""Persistence posouzení, kontext anotací a export (scénáře 13, 14, 15)."""

import io
import zipfile

import pandas as pd
import pytest
from synthetic_data import generate_synthetic

from rakathon.configuration import load_diagnosis_map, load_settings
from rakathon.data.dataset import prepare_dataset
from rakathon.domain import AnalysisConfig, BaselineConfig, ReviewStatus, SourceMode
from rakathon.pipeline import compute_analysis, compute_global
from rakathon.storage import exports
from rakathon.storage.csv_store import CsvStore, current_reviews, make_review, split_history

TRICKY = 'Pacient „P1“, čárka, "uvozovky";\nnový řádek – ěščřžýáíé\n=SUM(A1:A2)'


def _review(
    fp, pid="P0001", baseline="B-1", status=ReviewStatus.CLINICALLY_INTERESTING, comment=TRICKY, supersedes=""
):
    return make_review(
        dataset_fingerprint=fp,
        source_mode="real",
        patient_id=pid,
        baseline_config_id=baseline,
        analysis_id="A-1",
        analysis_label="test",
        status=status,
        comment=comment,
        reviewer="Dr. Ž",
        supersedes=supersedes,
    )


def test_review_roundtrip_preserves_text_and_survives_restart(tmp_path):
    fp = "f" * 64
    CsvStore(tmp_path, "real", fp).append_review(_review(fp))
    reloaded = CsvStore(tmp_path, "real", fp).load_reviews()  # nová instance = „restart“
    assert len(reloaded) == 1
    assert reloaded.at[0, "comment"] == TRICKY
    assert reloaded.at[0, "reviewer"] == "Dr. Ž"


def test_latest_review_wins_and_history_is_kept(tmp_path):
    fp = "a" * 64
    store = CsvStore(tmp_path, "real", fp)
    first = _review(fp, comment="první")
    store.append_review(first)
    store.append_review(
        _review(fp, status=ReviewStatus.DATA_ISSUE, comment="druhé", supersedes=first.record_id)
    )
    cur = current_reviews(store.load_reviews(), fp, "B-1")
    assert len(cur) == 1
    assert cur.iloc[0]["status"] == ReviewStatus.DATA_ISSUE.value
    assert cur.iloc[0]["supersedes"] == first.record_id
    hist, other = split_history(store.load_reviews(), "P0001", fp, "B-1")
    assert len(hist) == 2 and other.empty


def test_review_from_other_dataset_or_context_is_not_current(tmp_path):
    fp_a, fp_b = "a" * 64, "b" * 64
    CsvStore(tmp_path, "real", fp_a).append_review(_review(fp_a))
    # jiný dataset: jiný adresář, žádné zděděné posouzení pro stejné ID
    assert CsvStore(tmp_path, "real", fp_b).load_reviews().empty
    # jiný globální kontext ve stejném datasetu: jen historie
    reviews = CsvStore(tmp_path, "real", fp_a).load_reviews()
    assert current_reviews(reviews, fp_a, "B-other").empty
    hist, other = split_history(reviews, "P0001", fp_a, "B-other")
    assert hist.empty and len(other) == 1
    with pytest.raises(ValueError):
        CsvStore(tmp_path, "real", fp_b).append_review(_review(fp_a))


def test_excel_safe_only_touches_text_columns():
    df = pd.DataFrame(
        {"patient_id": ["P0001"], "residual": [-3.5], "comment": ["=HYPERLINK(1)"], "ok": ["text"]}
    )
    out = exports.excel_safe(df, ["comment", "ok"])
    assert out.at[0, "comment"] == "'=HYPERLINK(1)"
    assert out.at[0, "residual"] == -3.5
    assert out.at[0, "patient_id"] == "P0001"
    assert out.at[0, "ok"] == "text"


@pytest.fixture(scope="module")
def synthetic():
    s = load_settings()
    dx = load_diagnosis_map(s.diagnosis_map_path)
    bundle, _ = prepare_dataset(generate_synthetic().files, SourceMode.REAL, "demo", dx)
    g = compute_global(
        bundle, BaselineConfig(diagnosis_map_version=dx.version, diagnosis_map_hash=dx.content_hash), dx
    )
    return g, compute_analysis(g, AnalysisConfig(threshold=2.0))


def test_export_contains_exactly_selected_patients_in_order_with_config(synthetic, tmp_path):
    g, a = synthetic
    ids = a.scores.sort_values("score", ascending=False)["patient_id"].tolist()[:7][::-1]
    fp = g.dataset_fingerprint
    store = CsvStore(tmp_path, "real", fp)
    store.append_review(_review(fp, pid=ids[0], baseline=g.baseline_config_id))
    reviews = store.load_reviews()
    cur = current_reviews(reviews, fp, g.baseline_config_id)
    tables = {
        "patient_results.csv": exports.patient_results_table(g, ids),
        "analysis_results.csv": exports.analysis_results_table(g, a, cur, ids, "test view"),
        "reviews.csv": exports.reviews_export_table(reviews),
        "analysis_config.csv": exports.config_table(g, a, "test view", {"filtr": "x"}),
    }
    blob = exports.build_zip(tables, {"patient_order": ids})
    zf = zipfile.ZipFile(io.BytesIO(blob))
    assert {
        "patient_results.csv",
        "analysis_results.csv",
        "reviews.csv",
        "analysis_config.csv",
        "metadata.json",
        "README.txt",
    } <= set(zf.namelist())
    ar = pd.read_csv(
        io.BytesIO(zf.read("analysis_results.csv")), encoding="utf-8-sig", dtype={"patient_id": str}
    )
    assert ar["patient_id"].tolist() == ids
    assert set(ar["analysis_id"]) == {a.analysis_id}
    assert set(ar["baseline_config_id"]) == {g.baseline_config_id}
    assert set(ar["dataset_fingerprint"]) == {fp}
    assert ar.loc[0, "review_status"] == "Klinicky zajímavé"
    assert ar.loc[0, "review_comment"].startswith("Pacient")
    pr = pd.read_csv(io.BytesIO(zf.read("patient_results.csv")), encoding="utf-8-sig")
    assert list(dict.fromkeys(pr["patient_id"])) == ids
    assert set(pr["unit"]) == {"dny"}
    assert {"observed_available", "expected_available", "method_version", "feature_schema_version"} <= set(
        pr.columns
    )
    cfg = pd.read_csv(io.BytesIO(zf.read("analysis_config.csv")), encoding="utf-8-sig")
    assert '"threshold":2.0' in cfg.loc[0, "analysis_config_json"]
    assert "filtr" in cfg.loc[0, "filters_json"]
