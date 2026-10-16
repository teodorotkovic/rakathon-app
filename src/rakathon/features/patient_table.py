"""Agregovaná pacientská tabulka: jeden řádek na pacienta.

Epizody a laboratoře se agregují odděleně a teprve pak spojují přes patient_id
(validate="one_to_one"), takže join nemůže násobit počty pobytů ani délky.
"""

from __future__ import annotations

import pandas as pd

PATIENT_TABLE_KEYS = ["patient_id"]


def outcomes_wide(outcomes_long: pd.DataFrame) -> pd.DataFrame:
    wide = outcomes_long.pivot(
        index="patient_id",
        columns="metric_id",
        values=["observed", "support_n", "outcome_status", "outcome_reason"],
    )
    wide.columns = [f"{stat}__{metric}" for stat, metric in wide.columns]
    return wide.reset_index()


def build_patient_table(
    core: pd.DataFrame,
    context: pd.DataFrame,
    lab_summary: pd.DataFrame,
    extra: pd.DataFrame | None = None,
) -> pd.DataFrame:
    t = core.merge(context, on="patient_id", how="left", validate="one_to_one")
    t = t.merge(lab_summary, on="patient_id", how="left", validate="one_to_one")
    for col in [
        "n_lab_results",
        "n_lab_tests",
        "n_lab_days",
        "n_lab_flagged",
        "n_lab_low",
        "n_lab_high",
        "n_labs_without_episode",
    ]:
        # počet záznamů je u pacienta bez laboratoří skutečně 0; podíly zůstávají chybějící
        t[col] = t[col].fillna(0).astype(int)
    t["has_labs"] = t["has_labs"].fillna(False).astype(bool)
    if extra is not None and len(extra.columns) > 1:
        t = t.merge(extra, on="patient_id", how="left", validate="one_to_one")
    if t["patient_id"].duplicated().any():
        raise AssertionError("Pacientská tabulka musí mít jeden řádek na pacienta.")
    return t


def reserved_columns(patient_table: pd.DataFrame | None = None) -> set[str]:
    """Názvy, které doplňková vlastnost nesmí použít."""
    from rakathon.data.validation import EPISODE_COLUMNS, LAB_COLUMNS, PATIENT_COLUMNS

    names = set(PATIENT_COLUMNS) | set(EPISODE_COLUMNS) | set(LAB_COLUMNS)
    names |= {"observed", "expected", "residual", "log_residual", "score", "outlier", "status", "cluster_id"}
    if patient_table is not None:
        names |= set(patient_table.columns)
    return names
