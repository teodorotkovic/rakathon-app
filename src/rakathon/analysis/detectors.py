"""Lokální detektor odchylek nad rezidui vůči globální baseline.

RobustResidualDetector: pro každou zvolenou dimenzi (reziduum ukazatele) se na
lokální referenční kohortě odhadne medián a robustní měřítko 1.4826 × MAD
(fallback IQR/1.349; je-li i to nulové, dimenze se nestandardizuje). Skóre
pacienta = maximum |z| přes standardizovatelné dimenze; určující dimenze = argmax.
Skóre není aditivní a práh je pracovní heuristika, ne pravděpodobnost.

Směr odchylky se vždy určuje ze znaménka PŮVODNÍHO rezidua vůči baseline,
ne z lokálně centrovaného z-skóre.
"""

from __future__ import annotations

import numpy as np
import pandas as pd

from rakathon.analysis.residuals import DIRECTION_LABELS
from rakathon.domain import AnalysisConfig, BaselineStatus

EPS = 1e-9
MAD_FACTOR = 1.4826
IQR_FACTOR = 1.349

BAND_STRONG = "výrazná odchylka"
BAND_BORDERLINE = "hraniční odchylka"
BAND_NEAR = "těsně pod prahem"
BAND_NONE = "bez výrazné odchylky"
BAND_NOT_SCORED = "nehodnoceno"


def robust_scale(values: np.ndarray) -> tuple[float, float, str]:
    """Vrací (střed, měřítko, metoda). Měřítko NaN = dimenzi nelze standardizovat."""
    v = values[~np.isnan(values)]
    if len(v) == 0:
        return np.nan, np.nan, "none"
    center = float(np.median(v))
    mad = float(np.median(np.abs(v - center))) * MAD_FACTOR
    if mad > EPS:
        return center, mad, "MAD"
    q1, q3 = np.percentile(v, [25, 75])
    iqr = float(q3 - q1) / IQR_FACTOR
    if iqr > EPS:
        return center, iqr, "IQR"
    return center, np.nan, "none"


def _to_observed(expected: float, bound: float, scale: str) -> float:
    if np.isnan(expected) or np.isnan(bound):
        return np.nan
    val = np.expm1(np.log1p(expected) + bound) if scale == "log" else expected + bound
    return float(max(val, 0.0))


def run_robust_detector(results_long: pd.DataFrame, config: AnalysisConfig) -> dict:
    metrics = list(config.metrics)
    value_col = "log_residual" if config.scale == "log" else "residual"
    sub = results_long[results_long["metric_id"].isin(metrics)]
    patients = sorted(results_long["patient_id"].unique())

    def pivot(col: str) -> pd.DataFrame:
        return sub.pivot(index="patient_id", columns="metric_id", values=col).reindex(
            index=patients, columns=metrics
        )

    val = pivot(value_col).astype(float)
    raw_res = pivot("residual").astype(float)
    evaluable = pivot("evaluable").fillna(False).astype(bool)
    bstatus = pivot("baseline_status").fillna("")
    support = pivot("support_n").fillna(0)
    reasons = pivot("evaluability_reason").fillna("")

    # --- kdo je skórovatelný ---
    scorable = evaluable.all(axis=1)
    if not config.include_limited_reference:
        scorable &= (bstatus == BaselineStatus.OK.value).all(axis=1)
    not_scored_reason = pd.Series("", index=patients, dtype=object)
    for pid in patients:
        if scorable.at[pid]:
            continue
        msgs = []
        for m in metrics:
            if not evaluable.at[pid, m]:
                msgs.append(reasons.at[pid, m] or "výsledek nebo očekávání chybí")
            elif not config.include_limited_reference and bstatus.at[pid, m] != BaselineStatus.OK.value:
                msgs.append("omezená reference je v tomto pohledu vyloučena")
        not_scored_reason.at[pid] = "; ".join(dict.fromkeys(msgs))

    # --- lokální reference pro kalibraci ---
    scorable_ids = [p for p in patients if scorable.at[p]]
    if config.reference_ids is None:
        reference = scorable_ids
    else:
        wanted = set(config.reference_ids)
        reference = [p for p in scorable_ids if p in wanted]

    calibration_rows = []
    centers, scales = {}, {}
    calib_ok = len(reference) >= config.min_calibration_n
    for m in metrics:
        c, s, method = (
            robust_scale(val.loc[reference, m].to_numpy()) if reference else (np.nan, np.nan, "none")
        )
        centers[m], scales[m] = c, s
        calibration_rows.append(
            {
                "metric_id": m,
                "center": c,
                "scale": s,
                "scale_method": method,
                "n_reference": len(reference),
                "standardizable": bool(calib_ok and not np.isnan(s)),
            }
        )
    calibration = pd.DataFrame(calibration_rows)
    if not calib_ok:
        msg = (
            f"Lokální reference má jen {len(reference)} hodnotitelných pacientů "
            f"(minimum {config.min_calibration_n}) – standardizace není podložená."
        )
        for p in scorable_ids:
            not_scored_reason.at[p] = msg
        scorable_ids = []

    std_metrics = [m for m in metrics if calib_ok and not np.isnan(scales[m])]

    # --- dimenze ---
    dim_rows = []
    sub_idx = sub.set_index(["patient_id", "metric_id"])
    z = pd.DataFrame(np.nan, index=patients, columns=metrics)
    for m in std_metrics:
        z[m] = (val[m] - centers[m]) / scales[m]
    for pid in patients:
        for m in metrics:
            r = sub_idx.loc[(pid, m)]
            lo = hi = np.nan
            if m in std_metrics:
                lo_b = centers[m] - config.threshold * scales[m]
                hi_b = centers[m] + config.threshold * scales[m]
                lo = _to_observed(float(r["expected"]), lo_b, config.scale)
                hi = _to_observed(float(r["expected"]), hi_b, config.scale)
            dim_rows.append(
                {
                    "patient_id": pid,
                    "metric_id": m,
                    "observed": r["observed"],
                    "expected": r["expected"],
                    "residual": r["residual"],
                    "log_residual": r["log_residual"],
                    "value": val.at[pid, m],
                    "z": z.at[pid, m] if pid in scorable_ids else np.nan,
                    "center": centers[m],
                    "scale": scales[m],
                    "standardizable": m in std_metrics,
                    "support_n": support.at[pid, m],
                    "baseline_status": bstatus.at[pid, m],
                    "allowed_low": lo,
                    "allowed_high": hi,
                }
            )
    dims = pd.DataFrame(dim_rows)

    # --- skóre ---
    score_rows = []
    for pid in patients:
        row: dict = {"patient_id": pid, "in_reference": pid in reference}
        zs = z.loc[pid, std_metrics] if pid in scorable_ids else pd.Series(dtype=float)
        if pid in scorable_ids and len(std_metrics) == 0:
            not_scored_reason.at[pid] = (
                "Rozptyl lokální reference je nulový – standardizace není možná; "
                "zobrazeny jsou jen rozdíly v původních jednotkách."
            )
        if pid in scorable_ids and len(std_metrics) > 0:
            absz = zs.abs()
            driver = str(absz.idxmax())
            score = float(absz.max())
            direction = _direction(raw_res.at[pid, driver])
            notes = []
            if (bstatus.loc[pid, metrics] == BaselineStatus.LIMITED.value).any():
                notes.append("omezená reference")
            if (support.loc[pid, metrics] < config.min_support_stays).any():
                notes.append(f"méně než {config.min_support_stays} pobyty ve výpočtu")
            flags = [score >= t for t in config.sensitivity_thresholds]
            row.update(
                {
                    "scored": True,
                    "status": "scored",
                    "not_scored_reason": "",
                    "score": score,
                    "driver_metric": driver,
                    "outlier": score >= config.threshold,
                    "direction": direction,
                    "direction_label": DIRECTION_LABELS[direction],
                    "band": _band(score, config.threshold, config.margin),
                    "support_level": "omezená opora" if notes else "dobrá opora",
                    "support_notes": "; ".join(notes),
                    "sensitivity": " · ".join(
                        f"{t:g}{'✔' if f else '✘'}"
                        for t, f in zip(config.sensitivity_thresholds, flags, strict=True)
                    ),
                    "n_thresholds_flagged": int(sum(flags)),
                }
            )
        else:
            first_dir = _direction(raw_res.at[pid, metrics[0]])
            row.update(
                {
                    "scored": False,
                    "status": "not_scored",
                    "not_scored_reason": not_scored_reason.at[pid],
                    "score": np.nan,
                    "driver_metric": "",
                    "outlier": False,
                    "direction": first_dir,
                    "direction_label": DIRECTION_LABELS[first_dir],
                    "band": BAND_NOT_SCORED,
                    "support_level": "",
                    "support_notes": "",
                    "sensitivity": "",
                    "n_thresholds_flagged": 0,
                }
            )
        score_rows.append(row)
    scores = pd.DataFrame(score_rows)
    scored = scores[scores["scored"]].sort_values(["score", "patient_id"], ascending=[False, True])
    scores["rank"] = pd.Series(range(1, len(scored) + 1), index=scored.index)
    scores["rank"] = scores["rank"].astype("Int64")
    dims["is_driver"] = (
        dims.merge(scores[["patient_id", "driver_metric"]], on="patient_id", how="left")["driver_metric"]
        .eq(dims["metric_id"])
        .to_numpy()
    )
    return {"scores": scores, "dims": dims, "calibration": calibration, "reference_ids": tuple(reference)}


def _direction(residual: float) -> str:
    if residual is None or np.isnan(residual):
        return ""
    if residual > 0:
        return "longer"
    if residual < 0:
        return "shorter"
    return "equal"


def _band(score: float, threshold: float, margin: float) -> str:
    if score >= threshold + margin:
        return BAND_STRONG
    if score >= threshold:
        return BAND_BORDERLINE
    if score >= threshold - margin / 2:
        return BAND_NEAR
    return BAND_NONE
