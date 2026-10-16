"""Volitelná baseline Ridge (LOO): invariant vlastního výsledku, vzácné kategorie, rozklad predikce."""

import json
import math
from dataclasses import replace

import numpy as np
from builders import EpisodeBuilder, build_bundle, patient

from rakathon.domain import BaselineStatus
from rakathon.pipeline import compute_global


def _bundle(target_lengths, dxmap):
    eb = EpisodeBuilder()
    rows = []
    specs = [
        ("C91", "0-5", "M", 3),
        ("C91", "6-8", "F", 4),
        ("C91", "0-5", "F", 5),
        ("C91", "9-11", "M", 4),
        ("C91", "0-5", "M", 6),
        ("C91", "12-14", "F", 3),
        ("C91", "0-5", "M", 5),
        ("C91", "6-8", "M", 4),
        ("C92", "0-5", "M", 9),
        ("C92", "6-8", "F", 10),
        ("C92", "0-5", "F", 8),
        ("C92", "9-11", "M", 11),
        ("C92", "0-5", "M", 9),
        ("C73", "15-17", "F", 2),
    ]
    for i, (dx, age, sex, los) in enumerate(specs, start=2):
        pid = f"P{i:04d}"
        rows.append(patient(pid, dx=dx, age=age, sex=sex))
        eb.stays(pid, dx, [los, los])
    rows.append(patient("P0001", dx="C91", age="0-5", sex="M"))
    eb.stays("P0001", "C91", target_lengths)
    return build_bundle(rows, eb.rows, [], dxmap)


def _row(g, pid, metric="median_los_dx"):
    r = g.results_long
    return r[(r["patient_id"] == pid) & (r["metric_id"] == metric)].iloc[0]


def test_ridge_loo_own_outcome_does_not_change_expectation(dxmap, baseline_config):
    cfg = replace(baseline_config, method="ridge_loo")
    g1 = compute_global(_bundle([4, 4], dxmap), cfg, dxmap)
    g2 = compute_global(_bundle([40, 40], dxmap), cfg, dxmap)
    e1, e2 = _row(g1, "P0001"), _row(g2, "P0001")
    assert math.isclose(e1["expected"], e2["expected"])
    assert e1["residual"] != e2["residual"]
    assert e1["baseline_status"] == BaselineStatus.OK.value
    assert e1["expected"] >= 0


def test_ridge_decomposition_matches_prediction(dxmap, baseline_config):
    g = compute_global(_bundle([4, 4], dxmap), replace(baseline_config, method="ridge_loo"), dxmap)
    d = json.loads(_row(g, "P0001")["model_detail"])
    total = d["intercept"] + sum(t["contribution"] for t in d["terms"])
    assert math.isclose(total, d["pred_log"], rel_tol=1e-9)
    assert math.isclose(np.expm1(d["pred_log"]), _row(g, "P0001")["expected"], rel_tol=1e-9)
    assert d["train_n"] == 14  # všichni ostatní s výsledkem, bez hodnoceného pacienta


def test_ridge_rare_category_is_not_scored_without_crash(dxmap, baseline_config):
    g = compute_global(_bundle([4, 4], dxmap), replace(baseline_config, method="ridge_loo"), dxmap)
    rare = _row(g, "P0015")  # C73: jediný pacient své kategorie
    assert rare["baseline_status"] == BaselineStatus.INSUFFICIENT.value
    assert math.isnan(rare["expected"])
    limited = _row(g, "P0010")  # C92: 4 jiní v kategorii → omezená opora
    assert limited["baseline_status"] == BaselineStatus.LIMITED.value
