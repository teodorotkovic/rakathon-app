"""Lokální strukturální kontrola výpočtu na skutečných datech.

Nevypisuje pacientské řádky, jen souhrnné počty a výsledky kontrol. Nic nezapisuje.
Použití:  python -m uv run python scripts/check_real_data.py [--data-dir data]
"""

from __future__ import annotations

import argparse
import sys
from dataclasses import replace
from pathlib import Path

import numpy as np

from rakathon.configuration import (
    default_analysis_config,
    default_baseline_config,
    load_diagnosis_map,
    load_settings,
)
from rakathon.data.dataset import prepare_dataset
from rakathon.data.io import read_dataset_dir
from rakathon.domain import SourceMode
from rakathon.pipeline import compute_analysis, compute_global
from rakathon.storage import exports


def main() -> int:
    s = load_settings()
    ap = argparse.ArgumentParser()
    ap.add_argument("--data-dir", type=Path, default=s.data_dir)
    args = ap.parse_args()
    dx = load_diagnosis_map(s.diagnosis_map_path)
    bundle, report = prepare_dataset(read_dataset_dir(args.data_dir), SourceMode.REAL, "check", dx)
    checks: list[tuple[str, bool, str]] = []

    def check(name: str, ok: bool, detail: str = "") -> None:
        checks.append((name, bool(ok), detail))

    check("validace bez blokujících chyb", report.is_valid, f"{len(report.issues)} položek zprávy")
    if bundle is None:
        return _print(checks)
    cls = bundle.episodes["episode_class"].value_counts().to_dict()
    check("třídy epizod spočteny", sum(cls.values()) == len(bundle.episodes), str(cls))
    check(
        "délka pobytu jen u dokončených hospitalizací",
        bundle.episodes.loc[bundle.episodes["episode_class"] != "inpatient_completed", "los_days"]
        .isna()
        .all(),
    )
    check(
        "laboratoře se neztratily", len(bundle.labs) == len(bundle.raw["labs"]), f"{len(bundle.labs)} řádků"
    )

    cfg = default_baseline_config(s, dx)
    g = compute_global(bundle, cfg, dx)
    check(
        "pacientská tabulka 1 řádek/pacient",
        g.patient_table["patient_id"].is_unique,
        f"{len(g.patient_table)} pacientů",
    )
    r = g.results_long
    main_m = r[r["metric_id"] == "median_los_dx"]
    check(
        "chybějící výsledek není 0",
        not (main_m.loc[main_m["outcome_status"] == "no_relevant_stay", "observed"].fillna(-1) == 0).any(),
    )
    n_obs = int(main_m["observed"].notna().sum())
    check("pokrytí hlavního ukazatele", n_obs > 0, f"{n_obs}/{len(main_m)} pacientů s pozorováním")
    check(
        "žádný pacient ve vlastní referenci",
        all(
            pid not in str(refs).split(";")
            for pid, refs in zip(r["patient_id"], r["reference_ids"], strict=True)
        ),
    )
    check("stavy baseline", True, str(main_m["baseline_status"].value_counts().to_dict()))

    # LOO invariant: změna vlastního výsledku pacienta nezmění jeho očekávání
    eval_ids = main_m.loc[main_m["evaluable"], "patient_id"].tolist()
    if eval_ids:
        pid = eval_ids[0]
        mask = (bundle.episodes["patient_id"] == pid) & (
            bundle.episodes["episode_class"] == "inpatient_completed"
        )
        mod = replace(bundle)
        mod.episodes = bundle.episodes.copy()
        mod.episodes.loc[mask, "los_days"] = mod.episodes.loc[mask, "los_days"] * 10
        g2 = compute_global(mod, cfg, dx)
        e1 = main_m.set_index("patient_id").at[pid, "expected"]
        e2 = g2.results_long.query("metric_id == 'median_los_dx'").set_index("patient_id").at[pid, "expected"]
        check(
            "LOO: vlastní výsledek nemění vlastní očekávání", np.isclose(e1, e2), "1 náhodně zvolený pacient"
        )

    a = compute_analysis(g, default_analysis_config(s))
    check(
        "skóre konečná",
        np.isfinite(a.scores["score"].dropna()).all(),
        f"skórováno {int(a.scores['scored'].sum())}, nad prahem {int(a.scores['outlier'].sum())}",
    )
    check(
        "shlukování jen outlierů",
        set(a.clusters["patient_id"]) <= set(a.scores.loc[a.scores["outlier"], "patient_id"]),
        a.cluster_info.get("message", ""),
    )
    ids = a.scores["patient_id"].tolist()
    blob = exports.build_zip({"patient_results.csv": exports.patient_results_table(g, ids)}, {})
    check("export se sestaví", len(blob) > 0, f"{len(blob)} B (nezapsáno)")
    return _print(checks)


def _print(checks) -> int:
    ok_all = True
    for name, ok, detail in checks:
        ok_all &= ok
        print(f"[{'OK' if ok else 'CHYBA'}] {name}" + (f" – {detail}" if detail else ""))
    return 0 if ok_all else 1


if __name__ == "__main__":
    sys.exit(main())
