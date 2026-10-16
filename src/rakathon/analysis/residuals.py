"""Spojení pozorování a očekávání do long tabulky reziduí (pacient × ukazatel)."""

from __future__ import annotations

import numpy as np
import pandas as pd

from rakathon.domain import BaselineStatus

DIRECTION_LABELS = {
    "longer": "delší než očekávání",
    "shorter": "kratší než očekávání",
    "equal": "shodné s očekáváním",
    "": "",
}
DIRECTION_SYMBOLS = {"longer": "▲", "shorter": "▼", "equal": "●", "": ""}


def attach_residuals(baseline_long: pd.DataFrame, outcomes_long: pd.DataFrame) -> pd.DataFrame:
    t = baseline_long.merge(outcomes_long, on=["patient_id", "metric_id"], how="left", validate="one_to_one")
    obs = t["observed"].astype(float)
    exp = t["expected"].astype(float)
    t["residual"] = obs - exp
    # log1p je definováno pro nezáporné délky; obě strany jsou ≥ 0 z konstrukce.
    t["log_residual"] = np.log1p(obs) - np.log1p(exp)
    usable_status = t["baseline_status"].isin([BaselineStatus.OK.value, BaselineStatus.LIMITED.value])
    t["evaluable"] = obs.notna() & exp.notna() & usable_status
    reason = np.where(
        obs.isna(), t["outcome_reason"].fillna(""), np.where(exp.isna(), t["baseline_reason"].fillna(""), "")
    )
    t["evaluability_reason"] = reason
    t["direction"] = np.select(
        [t["residual"] > 0, t["residual"] < 0, t["residual"] == 0], ["longer", "shorter", "equal"], default=""
    )
    return t
