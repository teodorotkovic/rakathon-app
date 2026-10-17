"""Shlukování neobvyklých pacientů: koho, kolik shluků, proměnné, chybějící hodnoty, dendrogram, profil."""

from dataclasses import replace

import numpy as np
import pandas as pd
import pytest
from synthetic_data import generate_synthetic

from rakathon.analysis.clustering import cluster_outliers, cluster_profile, dendrogram_segments
from rakathon.configuration import load_diagnosis_map, load_settings
from rakathon.data.dataset import prepare_dataset
from rakathon.domain import AnalysisConfig, BaselineConfig, SourceMode
from rakathon.pipeline import compute_analysis, compute_global


def _toy(n_out: int = 8, nan_for: str | None = None):
    """8 neobvyklých (4 výrazně delší, 4 výrazně kratší) + 6 běžných pacientů."""
    ids = [f"P{i:04d}" for i in range(1, n_out + 7)]
    z = (
        [4.0, 4.5, 5.0, 5.5][: n_out // 2]
        + [-4.0, -4.5, -5.0, -5.5][: n_out - n_out // 2]
        + [0.1, -0.2, 0.3, 0, 0.5, -0.4]
    )
    outlier = [True] * n_out + [False] * 6
    scores = pd.DataFrame(
        {
            "patient_id": ids,
            "scored": True,
            "outlier": outlier,
            "band": ["výrazná odchylka"] * n_out + ["bez výrazné odchylky"] * 5 + ["těsně pod prahem"],
            "score": np.abs(z),
        }
    )
    dims = pd.DataFrame(
        {"patient_id": ids, "metric_id": "median_los_dx", "z": z, "residual": np.array(z) * 2}
    )
    table = pd.DataFrame(
        {
            "patient_id": ids,
            "age_order": [i % 6 for i in range(len(ids))],
            "n_inpatient_completed": 5,
            "n_stays_included": 3,
            "const": 1.0,
            "d70": [float(i % 3) for i in range(len(ids))],
        }
    )
    if nan_for:
        table.loc[table["patient_id"] == nan_for, "d70"] = np.nan
    return scores, dims, table


def test_toy_two_directions_and_only_outliers():
    scores, dims, table = _toy()
    out = cluster_outliers(scores, dims, table, AnalysisConfig())
    assert out.info["status"] == "clustered"
    assert set(out.assignments["patient_id"]) == set(scores.loc[scores["outlier"], "patient_id"])
    assert out.info["k"] == 2  # automaticky: dva jasně oddělené směry
    by_cluster = out.assignments.groupby("cluster_id")["patient_id"].apply(set).tolist()
    assert {"P0001", "P0002", "P0003", "P0004"} in by_cluster
    near = cluster_outliers(scores, dims, table, AnalysisConfig(cluster_include_near=True))
    assert "P0014" in set(near.assignments["patient_id"])  # těsně pod hranicí


def test_constant_feature_dropped_and_missing_values_excluded():
    scores, dims, table = _toy(nan_for="P0002")
    cfg = AnalysisConfig(cluster_features=("z:median_los_dx", "pt:const", "pt:d70"))
    out = cluster_outliers(scores, dims, table, cfg)
    assert ("pt:const", "u porovnatelných pacientů nemá rozptyl") in out.info["dropped_features"]
    assert out.info["features"] == ["z:median_los_dx", "pt:d70"]
    assert out.info["excluded"] == ["P0002"]
    assert "P0002" not in out.matrix.index
    row = out.assignments.set_index("patient_id").loc["P0002"]
    assert pd.isna(row["cluster_id"]) and row["isolated"]


def test_too_few_patients_do_not_form_clusters():
    scores, dims, table = _toy(n_out=3)
    out = cluster_outliers(scores, dims, table, AnalysisConfig(cluster_min_outliers=4))
    assert out.info["status"] == "too_few"
    assert out.assignments["isolated"].all()


def test_dendrogram_and_profile():
    scores, dims, table = _toy()
    out = cluster_outliers(
        scores, dims, table, AnalysisConfig(cluster_features=("z:median_los_dx", "pt:d70"))
    )
    leaf_cluster = dict(
        zip(out.assignments["patient_id"], out.assignments["cluster_id"].astype(int), strict=True)
    )
    segments, order = dendrogram_segments(out.linkage, list(out.matrix.index), leaf_cluster)
    assert len(segments) == len(out.matrix) - 1
    assert sorted(order) == sorted(out.matrix.index)
    assert segments[-1]["cluster"] is None  # kořen spojuje různé shluky
    assert out.info["cut_height"] is not None
    prof = cluster_profile(out.matrix, out.raw, out.assignments, out.features)
    assert len(prof) == out.info["k"] * 2
    c1 = out.assignments.loc[out.assignments["cluster_id"] == 1, "patient_id"]
    expected = out.matrix.loc[c1, "pt:d70"].mean() - out.matrix["pt:d70"].mean()
    got = prof[(prof["cluster_id"] == 1) & (prof["key"] == "pt:d70")]["std_diff"].iloc[0]
    assert got == pytest.approx(expected)


@pytest.fixture(scope="module")
def synthetic_global():
    s = load_settings()
    dx = load_diagnosis_map(s.diagnosis_map_path)
    bundle, _ = prepare_dataset(generate_synthetic().files, SourceMode.REAL, "demo", dx)
    return compute_global(
        bundle, BaselineConfig(diagnosis_map_version=dx.version, diagnosis_map_hash=dx.content_hash), dx
    )


@pytest.mark.parametrize("method", ["hierarchical", "kmeans"])
def test_methods_give_requested_number_of_clusters(synthetic_global, method):
    a = compute_analysis(synthetic_global, AnalysisConfig(cluster_method=method, cluster_k=3))
    assert a.cluster_info["status"] == "clustered"
    assert a.cluster_info["k"] == 3
    assert set(a.clusters["cluster_id"].dropna().astype(int)) == {1, 2, 3}
    outliers = set(a.scores.loc[a.scores["outlier"], "patient_id"])
    assert set(a.clusters["patient_id"]) <= outliers
    assert all(card["group"].startswith("Shluk") for card in a.group_cards)


def test_auto_k_is_deterministic_and_best_by_silhouette(synthetic_global):
    cfg = AnalysisConfig(metrics=("median_los_dx", "max_los_dx"))
    a1 = compute_analysis(synthetic_global, cfg)
    a2 = compute_analysis(synthetic_global, replace(cfg))
    pd.testing.assert_frame_equal(a1.clusters, a2.clusters)
    info = a1.cluster_info
    valid = {k: v for k, v in info["silhouette_by_k"].items() if not np.isnan(v)}
    assert 2 <= info["k"] <= 6
    assert info["k"] == max(valid, key=lambda k: (round(valid[k], 6), -k))


def test_cluster_settings_change_analysis_identity_not_baseline(synthetic_global):
    a1 = compute_analysis(synthetic_global, AnalysisConfig())
    a2 = compute_analysis(synthetic_global, AnalysisConfig(cluster_method="kmeans"))
    assert a1.analysis_id != a2.analysis_id
    assert a1.baseline_config_id == a2.baseline_config_id
