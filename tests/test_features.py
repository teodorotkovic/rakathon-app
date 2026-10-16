"""Agregace epizod a laboratoří (scénáře 4, 6, 7)."""

import math
from dataclasses import replace

from builders import EpisodeBuilder, build_bundle, cohort, lab, patient

from rakathon.domain import OutcomeStatus
from rakathon.pipeline import compute_analysis, compute_global


def test_many_labs_do_not_multiply_stays(dxmap, baseline_config):
    eb = EpisodeBuilder()
    eb.stays("P0001", "C91", [3, 5, 7])
    stay_ids = [r["episode_id"] for r in eb.rows if r["day_end"] != r["day_start"]]
    labs = [lab("P0001", 11, episode_id=stay_ids[i % 3]) for i in range(50)]
    g = compute_global(build_bundle([patient("P0001")], eb.rows, labs, dxmap), baseline_config, dxmap)
    row = g.patient_table.set_index("patient_id").loc["P0001"]
    assert row["n_stays_included"] == 3
    assert row["n_lab_results"] == 50
    obs = g.outcomes_long.set_index("metric_id")["observed"]
    assert obs["median_los_dx"] == 5
    assert obs["max_los_dx"] == 7
    assert len(g.patient_table) == 1


def test_birth_on_day_zero_is_not_treatment_start(dxmap, baseline_config):
    eb = EpisodeBuilder()
    eb.add("P0001", 0, 4, "Z38")  # porod: dokončená hospitalizace 4 dny
    eb.add("P0001", 400, 400, "R50")
    first_dx = eb.add("P0001", 900, 903, "C91")
    eb.add("P0001", 950, 953, "C91")
    bundle = build_bundle([patient("P0001")], eb.rows, [], dxmap)

    g = compute_global(bundle, baseline_config, dxmap)
    assert g.patient_table["first_episode_birth"].iloc[0]
    assert g.outcomes_long.set_index("metric_id").at["median_los_dx", "observed"] == 3
    assert "P0001-E001" not in set(g.selected_episodes["episode_id"])

    g2 = compute_global(bundle, replace(baseline_config, episode_rule="from_anchor_all_inpatient"), dxmap)
    assert g2.patient_table["anchor_episode_id"].iloc[0] == first_dx
    assert g2.patient_table["anchor_day"].iloc[0] == 900
    assert "P0001-E001" not in set(g2.selected_episodes["episode_id"])


def test_patient_without_relevant_stay_has_missing_outcome_not_zero(dxmap, baseline_config, analysis_config):
    eb = EpisodeBuilder()
    rows = cohort(10, "C91", 4, eb)
    rows.append(patient("P0099", dx="C91"))
    eb.add("P0099", 0, 0, "C91")
    eb.add("P0099", 30, 36, "D70")  # pobyt s jinou diagnózou nesmí vstoupit
    g = compute_global(build_bundle(rows, eb.rows, [], dxmap), baseline_config, dxmap)
    r = g.results_long[
        (g.results_long["patient_id"] == "P0099") & (g.results_long["metric_id"] == "median_los_dx")
    ]
    assert math.isnan(r["observed"].iloc[0])
    assert r["outcome_status"].iloc[0] == OutcomeStatus.NO_STAY.value
    assert not r["evaluable"].iloc[0]
    a = compute_analysis(g, analysis_config)
    s = a.scores.set_index("patient_id").loc["P0099"]
    assert not s["scored"] and not s["outlier"]
    assert s["not_scored_reason"]
