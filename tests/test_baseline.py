"""Peer baseline: LOO, jeden hlas na pacienta, hierarchie a malé reference (scénáře 8, 9)."""

import math

from builders import EpisodeBuilder, build_bundle, cohort, patient

from rakathon.domain import BaselineStatus
from rakathon.pipeline import compute_global


def _expected(g, pid, metric="median_los_dx"):
    r = g.results_long
    return r[(r["patient_id"] == pid) & (r["metric_id"] == metric)].iloc[0]


def _cohort_with_target(target_lengths, dxmap):
    eb = EpisodeBuilder()
    rows = []
    for i, los in enumerate([2, 3, 3, 4, 5, 5, 6, 8, 9], start=2):
        pid = f"P{i:04d}"
        rows.append(patient(pid))
        eb.stays(pid, "C91", [los, los])
    rows.append(patient("P0001"))
    eb.stays("P0001", "C91", target_lengths)
    return build_bundle(rows, eb.rows, [], dxmap)


def test_own_outcome_does_not_change_own_expectation(dxmap, baseline_config):
    g1 = compute_global(_cohort_with_target([4, 4], dxmap), baseline_config, dxmap)
    g2 = compute_global(_cohort_with_target([30, 30], dxmap), baseline_config, dxmap)
    e1, e2 = _expected(g1, "P0001"), _expected(g2, "P0001")
    assert e1["expected"] == e2["expected"] == 5
    assert "P0001" not in e1["reference_ids"].split(";")
    assert e1["residual"] != e2["residual"]
    assert e2["residual"] == 25


def test_each_patient_has_one_vote(dxmap, baseline_config):
    eb = EpisodeBuilder()
    rows = []
    for i in range(2, 10):
        pid = f"P{i:04d}"
        rows.append(patient(pid))
        eb.stays(pid, "C91", [2])
    rows.append(patient("P0010"))
    eb.stays("P0010", "C91", [20] * 22)  # mnoho dlouhých pobytů = stále jeden pacient
    rows.append(patient("P0001"))
    eb.stays("P0001", "C91", [3, 3])
    g = compute_global(build_bundle(rows, eb.rows, [], dxmap), baseline_config, dxmap)
    e = _expected(g, "P0001")
    assert e["reference_n"] == 9
    assert e["expected"] == 2


def test_fallback_reports_unused_factors(dxmap, baseline_config):
    eb = EpisodeBuilder()
    rows = []
    ages = ["0-5", "6-8", "9-11", "12-14", "15-17", "0-5", "6-8", "9-11", "12-14", "15-17"]
    for i, age in enumerate(ages, start=1):
        pid = f"P{i:04d}"
        rows.append(patient(pid, age=age, sex="M" if i % 2 else "F"))
        eb.stays(pid, "C91", [3, 4])
    g = compute_global(build_bundle(rows, eb.rows, [], dxmap), baseline_config, dxmap)
    e = _expected(g, "P0001")
    assert e["baseline_status"] == BaselineStatus.OK.value
    assert e["reference_level"] == 3  # jen přesná diagnóza
    assert "věková skupina" in e["factors_not_used"] and "pohlaví" in e["factors_not_used"]


def test_small_reference_and_unknown_diagnosis(dxmap, baseline_config):
    eb = EpisodeBuilder()
    rows = cohort(6, "C62", 3, eb, start_index=1)  # 5 peerů → omezená reference
    rows += cohort(2, "C73", 3, eb, start_index=20)  # 1 peer → nelze posoudit
    rows += cohort(1, "C99", 3, eb, start_index=30)  # nezařazená diagnóza, žádný peer
    g = compute_global(build_bundle(rows, eb.rows, [], dxmap), baseline_config, dxmap)
    limited = _expected(g, "P0001")
    assert limited["baseline_status"] == BaselineStatus.LIMITED.value
    assert limited["reference_n"] == 5
    small = _expected(g, "P0020")
    assert small["baseline_status"] == BaselineStatus.INSUFFICIENT.value
    assert math.isnan(small["expected"])
    unknown = _expected(g, "P0030")
    assert unknown["baseline_status"] == BaselineStatus.INSUFFICIENT.value
    assert "nezařazena" in unknown["baseline_reason"]
    assert not unknown["evaluable"]
