"""Import, validace a normalizace (scénáře 1, 2, 3, 5 + blokující chyby a fingerprint)."""

import math

from builders import EpisodeBuilder, build_bundle, cohort, lab, patient, to_files

from rakathon.data.dataset import prepare_dataset
from rakathon.data.io import fingerprint_files
from rakathon.domain import BaselineStatus, OutcomeStatus, Severity, SourceMode
from rakathon.pipeline import compute_global


def test_identifiers_and_test_code_stay_text(dxmap):
    eb = EpisodeBuilder()
    eb.stays("P0001", "C91", [3, 4])
    b = build_bundle([patient("P0001")], eb.rows, [lab("P0001", 5, code="00582")], dxmap)
    assert b.labs["test_code"].iloc[0] == "00582"
    assert b.raw["labs"]["test_code"].iloc[0] == "00582"
    assert b.patients["patient_id"].iloc[0] == "P0001"
    assert b.episodes["episode_id"].iloc[0] == "P0001-E001"


def test_episode_classification_and_length_without_plus_one(dxmap):
    eb = EpisodeBuilder()
    eb.add("P0001", 0, 0, "R50")  # ambulantní
    eb.add("P0001", 10, 14, "C91")  # dokončená hospitalizace, délka 4
    eb.add("P0001", 20, None, "C91")  # bez propuštění
    eb.add("P0001", 30, 28, "C91")  # neplatný interval
    bundle, report = prepare_dataset(
        to_files([patient("P0001")], eb.rows, []), SourceMode.SYNTHETIC, "t", dxmap
    )
    assert bundle is not None
    assert bundle.episodes["episode_class"].tolist() == [
        "outpatient",
        "inpatient_completed",
        "inpatient_open",
        "invalid_interval",
    ]
    los = bundle.episodes["los_days"].tolist()
    assert los[1] == 4
    assert all(math.isnan(x) for x in (los[0], los[2], los[3]))
    codes = {(i.code, i.severity) for i in report.issues}
    assert ("invalid_interval", Severity.WARNING) in codes
    assert ("open_stay", Severity.INFO) in codes


def test_labs_without_episode_negative_day_and_foreign_episode_are_kept(dxmap):
    eb = EpisodeBuilder()
    eb.stays("P0001", "C91", [3])
    other = eb.add("P0002", 0, 0, "R50")
    own = "P0001-E002"
    labs = [
        lab("P0001", 11, episode_id=own),
        lab("P0001", 50),  # mimo epizodu
        lab("P0001", -7),  # záporný den
        lab("P0001", 12, episode_id=other),  # epizoda cizího pacienta
    ]
    b = build_bundle([patient("P0001"), patient("P0002")], eb.rows, labs, dxmap)
    assert len(b.labs) == 4
    assert b.labs["episode_link"].tolist() == ["linked", "no_episode", "no_episode", "patient_mismatch"]
    assert b.labs["linked_episode_id"].tolist() == [own, "", "", ""]
    assert (b.labs["patient_id"] == "P0001").all()
    assert b.labs["day_num"].tolist()[2] == -7


def test_multi_tumor_patient_is_not_duplicated_or_used_in_baseline(dxmap, baseline_config):
    eb = EpisodeBuilder()
    rows = cohort(9, "C91", 4, eb, start_index=2)
    rows += [patient("P0001", dx="C91", tumor_id=1), patient("P0001", dx="C49", tumor_id=2)]
    eb.stays("P0001", "C91", [20, 20, 20])
    g = compute_global(build_bundle(rows, eb.rows, [], dxmap), baseline_config, dxmap)
    assert (g.core["patient_id"] == "P0001").sum() == 1
    assert (g.patient_table["patient_id"] == "P0001").sum() == 1
    r = g.results_long[g.results_long["patient_id"] == "P0001"]
    assert set(r["outcome_status"]) == {OutcomeStatus.EXCLUDED.value}
    assert set(r["baseline_status"]) == {BaselineStatus.EXCLUDED.value}
    refs = ";".join(g.results_long["reference_ids"])
    assert "P0001" not in refs
    assert g.selected_episodes[g.selected_episodes["patient_id"] == "P0001"].empty


def test_blocking_errors_reject_dataset(dxmap):
    eb = EpisodeBuilder()
    eb.stays("P0001", "C91", [3])
    dup = eb.rows + [dict(eb.rows[0])]
    bundle, report = prepare_dataset(to_files([patient("P0001")], dup, []), SourceMode.SYNTHETIC, "t", dxmap)
    assert bundle is None
    assert any(i.code == "duplicate_key" and i.severity == Severity.BLOCKING for i in report.issues)

    files = to_files([patient("P0001")], eb.rows, [])
    files["patients"] = b"patient_id,sex\nP0001,M\n"
    bundle, report = prepare_dataset(files, SourceMode.SYNTHETIC, "t", dxmap)
    assert bundle is None
    assert any(i.code == "missing_columns" for i in report.issues)


def test_fingerprint_depends_on_content():
    eb = EpisodeBuilder()
    eb.stays("P0001", "C91", [3])
    files = to_files([patient("P0001")], eb.rows, [])
    same = to_files([patient("P0001")], eb.rows, [])
    assert fingerprint_files(files) == fingerprint_files(same)
    changed = to_files([patient("P0001", sex="F")], eb.rows, [])
    assert fingerprint_files(files) != fingerprint_files(changed)
