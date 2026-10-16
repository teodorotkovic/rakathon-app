"""Souhrny laboratoří agregované na pacienta.

Jednotkou srovnání je pacient: pacient s 500 výsledky nemá 500 hlasů. Porovnává se
vždy stejný test_code se stejnou jednotkou; jednotky se bez ověřeného převodu neslučují.
Chybějící laboratoř = není dostupný záznam, ne normální výsledek.
"""

from __future__ import annotations

import numpy as np
import pandas as pd


def _usable(labs: pd.DataFrame) -> pd.DataFrame:
    return labs[labs["known_patient"] & labs["value_num"].notna()]


def lab_patient_summary(labs: pd.DataFrame) -> pd.DataFrame:
    lab = _usable(labs)
    flagged = lab["flag"].isin(["L", "N", "H"])
    g = lab.assign(
        is_low=(lab["flag"] == "L") & flagged,
        is_high=(lab["flag"] == "H") & flagged,
        flagged=flagged,
        no_episode=lab["episode_link"] != "linked",
    ).groupby("patient_id")
    out = pd.DataFrame(
        {
            "n_lab_results": g.size(),
            "n_lab_tests": g["test_key"].nunique(),
            "n_lab_days": g["day_num"].nunique(),
            "n_lab_flagged": g["flagged"].sum(),
            "n_lab_low": g["is_low"].sum(),
            "n_lab_high": g["is_high"].sum(),
            "n_labs_without_episode": g["no_episode"].sum(),
            "lab_day_min": g["day_num"].min().astype(float),
            "lab_day_max": g["day_num"].max().astype(float),
        }
    )
    denom = out["n_lab_flagged"].replace(0, np.nan)
    out["lab_share_low"] = out["n_lab_low"] / denom
    out["lab_share_high"] = out["n_lab_high"] / denom
    out["has_labs"] = True
    out.index.name = "patient_id"
    return out.reset_index()


def lab_test_patient_medians(labs: pd.DataFrame) -> pd.DataFrame:
    """Jeden řádek na pacienta × test (kód + jednotka)."""
    lab = _usable(labs)
    flagged = lab["flag"].isin(["L", "N", "H"])
    g = lab.assign(outside=lab["flag"].isin(["L", "H"]), flagged=flagged).groupby(
        ["patient_id", "test_key", "test_code", "panel", "unit", "test_label"], observed=True
    )
    out = g.agg(
        n_results=("value_num", "size"),
        median_value=("value_num", "median"),
        n_flagged=("flagged", "sum"),
        n_outside=("outside", "sum"),
    ).reset_index()
    out["share_outside"] = out["n_outside"] / out["n_flagged"].replace(0, np.nan)
    return out


def lab_test_catalog(labs: pd.DataFrame) -> pd.DataFrame:
    lab = _usable(labs)
    cat = lab.groupby(["test_key", "test_code", "panel", "unit", "test_label"], observed=True).agg(
        n_results=("value_num", "size"), n_patients=("patient_id", "nunique")
    )
    return cat.reset_index().sort_values(["n_patients", "n_results"], ascending=False).reset_index(drop=True)
