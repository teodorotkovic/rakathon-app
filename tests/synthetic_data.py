"""Generátor nezávisle vymyšlených syntetických dat – POUZE pro automatické testy.

Aplikace syntetická data nepoužívá ani negeneruje.

Data nejsou odvozena ze skutečných pacientských řádků. Generátor má pevný seed a
vytváří konzistentní tři tabulky s různými diagnózami, běžnými i neobvyklými
průběhy, malou referencí, chybějícími daty a několika skupinovými vzorci.
Tabulka `truth` slouží výhradně testům – baseline ani detektor ji nedostávají.
"""

from __future__ import annotations

from dataclasses import dataclass

import numpy as np
import pandas as pd

from rakathon.data.io import dataframe_to_csv_bytes
from rakathon.data.validation import AGE_GROUPS, EPISODE_COLUMNS, LAB_COLUMNS, PATIENT_COLUMNS

DEFAULT_SEED = 20261017

# kód, počet pacientů, typická délka pobytu (dny), topografie, morfologie (smyšlené kombinace)
DX_PLAN = [
    ("C91", 24, 5.0, "C42.1", "9836/3"),
    ("C92", 10, 9.0, "C42.1", "9861/3"),
    ("C81", 10, 3.0, "C77.1", "9650/3"),
    ("C83", 6, 4.0, "C77.2", "9680/3"),
    ("C84", 4, 4.0, "C77.0", "9714/3"),
    ("C71", 14, 6.0, "C71.6", "9470/3"),
    ("D43", 5, 4.0, "C71.0", "9421/1"),
    ("C40", 8, 5.0, "C40.2", "9180/3"),
    ("C41", 5, 5.0, "C41.4", "9260/3"),
    ("C49", 9, 4.0, "C49.2", "8910/3"),
    ("C64", 9, 3.0, "C64.9", "8960/3"),
    ("C62", 7, 2.0, "C62.9", "9071/3"),
    ("C22", 3, 6.0, "C22.0", "8970/3"),
    ("C74", 3, 4.0, "C74.9", "9500/3"),
    ("C73", 1, 2.0, "C73.9", "8260/3"),
    ("D48", 2, 3.0, "C49.9", "8815/1"),
]

# test_code, panel, jednotka, ref_low, ref_high, typická hodnota, rozptyl
LAB_TESTS = [
    ("00582", "biochemistry", "ukat/l", 0.25, 0.58, 0.40, 0.10),
    ("03086", "biochemistry", "mmol/l", 2.8, 8.1, 5.0, 1.2),
    ("08574", "biochemistry", "umol/l", 45.0, 84.0, 60.0, 12.0),
    ("01675", "blood_count", "x10 12/l", 3.8, 5.2, 4.4, 0.4),
    ("04471", "blood_count", "x10 9/l", 4.0, 10.0, 6.5, 1.8),
    ("02218", "coagulation", "s", 25.0, 37.0, 31.0, 3.0),
    ("06102", "differential", "%", 40.0, 75.0, 58.0, 9.0),
]

OUTPATIENT_CODES = ["Z51", "Z09", "Z08", "R50", "J06", "Z00"]


@dataclass
class SyntheticDataset:
    files: dict[str, bytes]
    patients: pd.DataFrame
    episodes: pd.DataFrame
    labs: pd.DataFrame
    truth: pd.DataFrame


def generate_synthetic(seed: int = DEFAULT_SEED) -> SyntheticDataset:
    rng = np.random.default_rng(seed)
    plan: list[dict] = []
    for code, n, base, topo, morph in DX_PLAN:
        for _ in range(n):
            plan.append({"dx": code, "base": base, "topo": topo, "morph": morph, "pattern": "typical"})
    order = rng.permutation(len(plan))
    plan = [plan[i] for i in order]

    def assign(pattern: str, dx_codes: list[str], count: int) -> None:
        hits = [p for p in plan if p["dx"] in dx_codes and p["pattern"] == "typical"][:count]
        for p in hits:
            p["pattern"] = pattern

    assign("long_stays_d70", ["C91"], 5)
    assign("short_stays", ["C71"], 2)
    assign("short_stays", ["C40"], 2)
    assign("isolated_long", ["C64"], 1)
    assign("isolated_short", ["C92"], 1)
    assign("no_relevant_stay", ["C81", "C49", "C64", "C91"], 6)
    assign("single_stay", ["C83", "C41", "C62", "C71"], 4)

    patient_rows, episode_rows, lab_rows, truth_rows = [], [], [], []
    for i, p in enumerate(plan):
        pid = f"P{5001 + i:04d}"
        p["pid"] = pid
        age = AGE_GROUPS[int(rng.choice(6, p=[0.35, 0.12, 0.12, 0.17, 0.2, 0.04]))]
        sex = "M" if rng.random() < 0.55 else "F"
        patient_rows.append(_patient_row(pid, 1, sex, age, p, rng))
        truth_rows.append({"patient_id": pid, "planted_pattern": p["pattern"]})
        episode_rows.extend(_episodes_for(pid, p, age, rng))

    # Pacient se dvěma nádory: zobrazí se, ale vyřadí z baseline.
    pid = f"P{5001 + len(plan):04d}"
    p_multi = {
        "dx": "C91",
        "base": 5.0,
        "topo": "C42.1",
        "morph": "9836/3",
        "pattern": "multi_tumor",
        "pid": pid,
    }
    patient_rows.append(_patient_row(pid, 1, "F", "6-8", p_multi, rng))
    patient_rows.append(
        _patient_row(pid, 2, "F", "12-14", {"dx": "C49", "topo": "C49.2", "morph": "8910/3"}, rng)
    )
    truth_rows.append({"patient_id": pid, "planted_pattern": "multi_tumor"})
    episode_rows.extend(_episodes_for(pid, p_multi, "6-8", rng))

    episodes = pd.DataFrame(episode_rows, columns=EPISODE_COLUMNS)
    # Jeden neplatný interval (konec před začátkem) pro audit.
    idx = episodes.index[(episodes["day_end"] == episodes["day_start"]) & (episodes["day_start"] != "0")][7]
    episodes.loc[idx, "day_end"] = str(int(episodes.loc[idx, "day_start"]) - 2)

    pattern_by_pid = {p["pid"]: p["pattern"] for p in plan}
    lab_pids = [p["pid"] for p in plan if rng.random() < 0.45 or p["pattern"] == "long_stays_d70"]
    for k, lpid in enumerate(lab_pids):
        heavy = k == 0
        lab_rows.extend(
            _labs_for(
                lpid,
                episodes[episodes["patient_id"] == lpid],
                pattern_by_pid[lpid],
                heavy,
                negative=k in (1, 2),
                rng=rng,
            )
        )

    patients = pd.DataFrame(patient_rows, columns=PATIENT_COLUMNS)
    labs = pd.DataFrame(lab_rows, columns=LAB_COLUMNS)
    files = {
        "patients": dataframe_to_csv_bytes(patients),
        "episodes": dataframe_to_csv_bytes(episodes),
        "labs": dataframe_to_csv_bytes(labs),
    }
    return SyntheticDataset(files, patients, episodes, labs, pd.DataFrame(truth_rows))


def _patient_row(pid: str, tumor_id: int, sex: str, age: str, p: dict, rng: np.random.Generator) -> dict:
    staged = rng.random() < 0.18
    return {
        "patient_id": pid,
        "tumor_id": str(tumor_id),
        "sex": sex,
        "age_group": age,
        "dx_icd10": p["dx"],
        "topography_icdo3": p["topo"],
        "morphology_icdo3": "3333/3" if rng.random() < 0.04 else p["morph"],
        "laterality": str(rng.choice(["4", "4", "4", "1", "2"])),
        "grade": str(rng.choice(["9", "9", "9", "5", "6", "1", "3", ""])),
        "stage": str(rng.choice(["1A", "2", "2A", "3", "4"]))
        if staged
        else str(rng.choice(["7", "7", "7", "9"])),
        "extent": str(rng.choice(["1", "2", "", "9"])),
        "t": "X" if staged else "",
        "n": str(rng.choice(["0", "X"])) if staged else "",
        "m": "0" if staged else "",
        "pt": "",
        "pn": "",
        "psu": "",
        "pm": "",
        "deceased": "0",
    }


def _episodes_for(pid: str, p: dict, age: str, rng: np.random.Generator) -> list[dict]:
    rows: list[dict] = []
    pattern = p["pattern"]
    factor = {"long_stays_d70": 3.0, "short_stays": 0.3, "isolated_long": 4.0, "isolated_short": 0.2}.get(
        pattern, 1.0
    )
    patient_effect = float(rng.lognormal(0, 0.18))

    def add(start: int, end: int | None, dx: str) -> None:
        rows.append(
            {
                "patient_id": pid,
                "episode_id": f"{pid}-E{len(rows) + 1:03d}",
                "day_start": str(start),
                "day_end": "" if end is None else str(end),
                "dx_main": dx,
            }
        )

    birth = age == "0-5" and rng.random() < 0.3
    if birth:
        add(0, int(rng.integers(2, 5)), "Z38")
        day = int(rng.integers(200, 1500))
    else:
        add(0, 0, str(rng.choice(["R50", "R10", p["dx"]])))
        day = int(rng.integers(1, 20))

    if pattern == "no_relevant_stay":
        n_stays = 0
    elif pattern == "single_stay":
        n_stays = 1
    else:
        n_stays = int(rng.integers(3, 12))
    open_stay = rng.random() < 0.03
    for s in range(n_stays):
        for _ in range(int(rng.integers(1, 4))):
            add(day, day, str(rng.choice(OUTPATIENT_CODES + [p["dx"]])))
            day += int(rng.integers(2, 10))
        los = max(1, int(round(rng.lognormal(np.log(p["base"] * factor * patient_effect), 0.3))))
        dx_main = p["dx"] if rng.random() < 0.9 else "Z51"
        if open_stay and s == n_stays - 1:
            add(day, None, dx_main)
            day += 30
        else:
            add(day, day + los, dx_main)
            day += los + int(rng.integers(3, 15))
        if pattern == "long_stays_d70" or rng.random() < 0.08:
            d70_los = int(rng.integers(3, 9))
            add(day, day + d70_los, "D70")
            day += d70_los + int(rng.integers(3, 10))
    if pattern == "no_relevant_stay":
        for _ in range(int(rng.integers(1, 3))):  # pobyty s jinou diagnózou – nesmí vstoupit do ukazatele
            los = int(rng.integers(1, 6))
            add(day, day + los, str(rng.choice(["J18", "D70", "Z51"])))
            day += los + int(rng.integers(5, 20))
    for _ in range(int(rng.integers(5, 30))):
        add(day, day, str(rng.choice(OUTPATIENT_CODES + [p["dx"], ""])))
        day += int(rng.integers(20, 90))
    return rows


def _labs_for(
    pid: str, eps: pd.DataFrame, pattern: str, heavy: bool, negative: bool, rng: np.random.Generator
) -> list[dict]:
    rows: list[dict] = []
    n_tests = int(rng.integers(2, 5))
    tests = [LAB_TESTS[i] for i in rng.choice(len(LAB_TESTS), size=n_tests, replace=False)]
    if pattern == "long_stays_d70" and LAB_TESTS[4] not in tests:
        tests.append(LAB_TESTS[4])
    starts = eps["day_start"].astype(int).to_numpy()
    ends = pd.to_numeric(eps["day_end"].replace("", np.nan)).to_numpy()
    for code, panel, unit, lo, hi, mu, sd in tests:
        n = int(rng.integers(30, 60)) if heavy else int(rng.integers(1, 7))
        for _ in range(n):
            j = int(rng.integers(0, len(eps)))
            day = int(starts[j]) + (
                int(rng.integers(0, max(1, int(ends[j] - starts[j]) + 1))) if not np.isnan(ends[j]) else 0
            )
            within = (starts <= day) & ((ends >= day) | np.isnan(ends))
            episode_id = (
                eps["episode_id"].iloc[int(np.argmax(within))] if within.any() and rng.random() > 0.35 else ""
            )
            if negative and rng.random() < 0.3:
                day, episode_id = -int(rng.integers(1, 40)), ""
            mean = mu * (0.45 if (pattern == "long_stays_d70" and code == "04471") else 1.0)
            value = round(max(0.01, float(rng.normal(mean, sd))), 2)
            has_range = rng.random() > 0.04
            flag = ("L" if value < lo else "H" if value > hi else "N") if has_range else ""
            rows.append(
                {
                    "patient_id": pid,
                    "episode_id": episode_id,
                    "day": str(day),
                    "test_code": code,
                    "panel": panel,
                    "value": f"{value}",
                    "unit": unit,
                    "ref_low": f"{lo}" if has_range else "",
                    "ref_high": f"{hi}" if has_range else "",
                    "flag": flag,
                }
            )
    return rows
