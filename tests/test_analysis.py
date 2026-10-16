"""Lokální detektor, stavy bez pádu, oddělení globálního a lokálního, shlukování (scénáře 9, 10, 11)."""

from dataclasses import replace

import numpy as np
import pandas as pd
import pandas.testing as pdt
import pytest
from builders import EpisodeBuilder, build_bundle, cohort

from rakathon.analysis.detectors import robust_scale, run_robust_detector
from rakathon.configuration import load_diagnosis_map, load_settings
from rakathon.data.dataset import prepare_dataset
from synthetic_data import generate_synthetic
from rakathon.domain import AnalysisConfig, BaselineConfig, SourceMode
from rakathon.pipeline import compute_analysis, compute_global


def _results(residuals: dict[str, float], status="ok", support=3) -> pd.DataFrame:
    rows = []
    for pid, res in residuals.items():
        exp = 5.0
        obs = exp + res if not np.isnan(res) else np.nan
        rows.append(
            {
                "patient_id": pid,
                "metric_id": "median_los_dx",
                "observed": obs,
                "expected": exp,
                "residual": obs - exp,
                "log_residual": np.log1p(obs) - np.log1p(exp),
                "evaluable": not np.isnan(res),
                "baseline_status": status,
                "support_n": support,
                "evaluability_reason": "" if not np.isnan(res) else "Žádná dokončená hospitalizace",
            }
        )
    return pd.DataFrame(rows)


def test_robust_scale_fallbacks():
    c, s, m = robust_scale(np.array([1.0, 2.0, 3.0, 4.0, 10.0]))
    assert m == "MAD" and s > 0
    c, s, m = robust_scale(np.array([0.0] * 7 + [1.0, 2.0, 3.0]))
    assert m == "IQR" and s > 0
    c, s, m = robust_scale(np.array([0.0] * 10))
    assert m == "none" and np.isnan(s)


def test_constant_metric_gives_no_infinite_scores():
    res = _results({f"P{i:04d}": 0.0 for i in range(1, 12)})
    out = run_robust_detector(res, AnalysisConfig(scale="raw"))
    assert not out["scores"]["scored"].any()
    assert not out["scores"]["outlier"].any()
    assert np.isfinite(out["scores"]["score"].fillna(0)).all()
    assert "nulový" in out["scores"]["not_scored_reason"].iloc[0]


def test_missing_dimension_and_small_calibration_are_not_scored():
    vals = {f"P{i:04d}": float(i % 4) for i in range(1, 12)}
    vals["P0099"] = np.nan
    out = run_robust_detector(_results(vals), AnalysisConfig())
    s = out["scores"].set_index("patient_id")
    assert not s.at["P0099", "scored"]
    assert "hospitalizace" in s.at["P0099", "not_scored_reason"]

    few = _results({f"P{i:04d}": float(i) for i in range(1, 5)})
    out = run_robust_detector(few, AnalysisConfig())
    assert not out["scores"]["scored"].any()
    assert "Lokální reference má jen 4" in out["scores"]["not_scored_reason"].iloc[0]


def test_zero_outliers_is_a_valid_result(dxmap, baseline_config):
    eb = EpisodeBuilder()
    rows = cohort(12, "C91", 4, eb)
    g = compute_global(build_bundle(rows, eb.rows, [], dxmap), baseline_config, dxmap)
    a = compute_analysis(g, AnalysisConfig())
    assert a.scores["outlier"].sum() == 0
    assert a.cluster_info["status"] in ("no_outliers",)
    assert a.group_cards == []


def test_direction_comes_from_raw_residual_not_local_z():
    vals = {f"P{i:04d}": 3.0 + 0.1 * (i % 3) for i in range(1, 12)}  # reference centrovaná kolem +3 dnů
    vals["P0050"] = 0.2  # stále delší než očekávání, ale hluboko pod lokálním středem
    out = run_robust_detector(_results(vals), AnalysisConfig(scale="raw"))
    s = out["scores"].set_index("patient_id").loc["P0050"]
    z = out["dims"].set_index("patient_id").at["P0050", "z"]
    assert z < 0 and s["outlier"]
    assert s["direction"] == "longer"


@pytest.fixture(scope="module")
def synthetic_global():
    s = load_settings()
    dx = load_diagnosis_map(s.diagnosis_map_path)
    bundle, _ = prepare_dataset(generate_synthetic().files, SourceMode.REAL, "demo", dx)
    cfg = BaselineConfig(diagnosis_map_version=dx.version, diagnosis_map_hash=dx.content_hash)
    return compute_global(bundle, cfg, dx), bundle, cfg, dx


def test_local_analysis_never_changes_global_baseline(synthetic_global):
    g, bundle, cfg, dx = synthetic_global
    before = g.results_long.copy()
    a_default = compute_analysis(g, AnalysisConfig())
    subset = tuple(sorted(a_default.scores.loc[a_default.scores["scored"], "patient_id"])[:40])
    a_local = compute_analysis(g, AnalysisConfig(reference_ids=subset, threshold=2.0))
    pdt.assert_frame_equal(g.results_long, before)
    g_again = compute_global(bundle, cfg, dx)
    pdt.assert_frame_equal(g_again.results_long.drop(columns=[]), before, check_like=False)
    assert a_local.reference_ids == subset
    assert a_local.analysis_id != a_default.analysis_id
    assert not a_local.calibration["center"].equals(
        a_default.calibration["center"]
    ) or not a_local.calibration["scale"].equals(a_default.calibration["scale"])


def test_clustering_uses_only_outliers_and_does_not_invent_groups(synthetic_global):
    g, *_ = synthetic_global
    a = compute_analysis(g, AnalysisConfig(metrics=("median_los_dx", "max_los_dx")))
    outliers = set(a.scores.loc[a.scores["outlier"], "patient_id"])
    assert set(a.clusters["patient_id"]) <= outliers
    for card in a.group_cards:
        assert set(card["members"]) <= outliers and card["n"] >= 2

    strict = compute_analysis(g, AnalysisConfig(threshold=6.0))
    n_out = int(strict.scores["outlier"].sum())
    assert n_out < 4
    assert strict.cluster_info["status"] in ("too_few", "no_outliers")
    assert strict.group_cards == []
    assert strict.clusters["cluster_id"].isna().all()


def test_include_limited_reference_toggle(synthetic_global):
    g, *_ = synthetic_global
    with_limited = compute_analysis(g, AnalysisConfig())
    without = compute_analysis(g, replace(AnalysisConfig(), include_limited_reference=False))
    assert without.scores["scored"].sum() < with_limited.scores["scored"].sum()
    excluded = without.scores[~without.scores["scored"] & with_limited.scores["scored"]]
    assert excluded["not_scored_reason"].str.contains("omezená reference").all()
