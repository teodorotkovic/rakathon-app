"""Deterministická vysvětlení ve třech oddělených vrstvách.

A. Proč právě toto očekávání (reference globální baseline).
B. Co vyvolává označení odchylky (lokální detektor; skóre = maximum, ne součet).
C. Čím se pacient/skupina liší (deskriptivní souvislosti = hypotézy, ne příčiny).

Všechna čísla v textech pocházejí z výpočtu; nic se negeneruje jazykovým modelem.
"""

from __future__ import annotations

import json
from collections.abc import Callable

import numpy as np
import pandas as pd

from rakathon.analysis.residuals import DIRECTION_LABELS
from rakathon.domain import AnalysisConfig, BaselineStatus
from rakathon.formatting import (
    fmt_days,
    fmt_num,
    fmt_pct,
    fmt_pp,
    fmt_signed,
    fmt_signed_days,
    patients_word,
)

LabelFn = Callable[[str], str]

# ---------------------------------------------------------------------------
# A. Proč právě toto očekávání?
# ---------------------------------------------------------------------------


def explain_expectation(row: pd.Series, metric_label: str) -> str:
    status = row["baseline_status"]
    if status == BaselineStatus.EXCLUDED.value:
        return f"**{metric_label}:** očekávání se nepočítá. {row['baseline_reason']}"
    if status == BaselineStatus.INSUFFICIENT.value:
        txt = f"**{metric_label}:** nelze posoudit – {row['baseline_reason']}"
        if pd.notna(row.get("population_median")):
            txt += (
                f" Pouze pro orientaci: medián všech ostatních pacientů s dostupným výsledkem je "
                f"{fmt_days(row['population_median'])}; nejde o klinicky srovnatelné očekávání."
            )
        return txt
    detail = row.get("model_detail")
    if isinstance(detail, str) and detail:
        return _explain_model(row, json.loads(detail), metric_label)
    n = int(row["reference_n"])
    txt = (
        f"**{metric_label}:** očekávání {fmt_days(row['expected'])} = medián hodnot {n} {patients_word(n)} "
        f"se shodnými charakteristikami ({row['factors_used']}). Hodnocený pacient do reference nepatří."
    )
    if row["factors_not_used"]:
        level = int(row["reference_level"])
        why = (
            "na podrobnější úrovni bylo méně srovnatelných pacientů, než vyžaduje hranice reference"
            if level > 1
            else "nejsou součástí zvolené hierarchie"
        )
        txt += f" Samostatně **nejsou zohledněny**: {row['factors_not_used']} ({why})."
    txt += (
        f" Rozložení hodnot v referenci: kvartily {fmt_num(row['ref_q1'])}–{fmt_num(row['ref_q3'])}, "
        f"rozsah {fmt_num(row['ref_min'])}–{fmt_num(row['ref_max'])} dní "
        "(rozložení pozorovaných hodnot, ne kalibrovaný predikční interval)."
    )
    if status == BaselineStatus.LIMITED.value:
        txt += f" ⚠ {row['baseline_reason']}"
    return txt


def model_terms_table(detail: dict) -> pd.DataFrame:
    """Rozklad predikce regrese: základ + příspěvky v log1p škále a jako násobek (1 + délka)."""
    rows = [
        {
            "Složka": "základ modelu",
            "Hodnota": "",
            "Příspěvek (log1p)": detail["intercept"],
            "Násobek (1 + délka)": float(np.exp(detail["intercept"])),
        }
    ]
    for t in detail["terms"]:
        rows.append(
            {
                "Složka": t["factor"],
                "Hodnota": t["value"] + ("" if t["seen_in_training"] else " (nevidáno)"),
                "Příspěvek (log1p)": t["contribution"],
                "Násobek (1 + délka)": float(np.exp(t["contribution"])),
            }
        )
    rows.append(
        {
            "Složka": "součet = predikce",
            "Hodnota": "",
            "Příspěvek (log1p)": detail["pred_log"],
            "Násobek (1 + délka)": float(np.exp(detail["pred_log"])),
        }
    )
    return pd.DataFrame(rows)


def _explain_model(row: pd.Series, detail: dict, metric_label: str) -> str:
    parts = [f"{t['factor']} {t['value']} ×{fmt_num(np.exp(t['contribution']), 2)}" for t in detail["terms"]]
    txt = (
        f"**{metric_label}:** modelové typické očekávání {fmt_days(row['expected'])} (Ridge regrese v log1p škále, "
        f"natrénovaná na {detail['train_n']} jiných pacientech – hodnocený pacient v modelu není). "
        f"Rozklad téže predikce: základ ≈ {fmt_days(np.expm1(detail['intercept']))}; "
        + "; ".join(parts)
        + " (násobky platí pro 1 + délku pobytu; je to typická hodnota modelu, ne aritmetický průměr)."
    )
    n = int(row["reference_n"])
    txt += (
        f" Pro srovnání: {n} {patients_word(n)} se stejnou diagnostickou kategorií má kvartily "
        f"{fmt_num(row['ref_q1'])}–{fmt_num(row['ref_q3'])} dní."
    )
    if row["factors_not_used"]:
        txt += f" Nezohledněno: {row['factors_not_used']}."
    if row["baseline_reason"]:
        txt += f" ⚠ {row['baseline_reason']}"
    return txt


# ---------------------------------------------------------------------------
# B. Co vyvolává označení?
# ---------------------------------------------------------------------------


def explain_flag(
    score_row: pd.Series, dims_rows: pd.DataFrame, config: AnalysisConfig, metric_labels: dict[str, str]
) -> dict:
    """Vrací {'summary': str, 'table': DataFrame, 'counterfactual': str}."""
    rows = []
    for d in dims_rows.itertuples(index=False):
        label = metric_labels.get(d.metric_id, d.metric_id)
        rows.append(
            {
                "Ukazatel": label,
                "Pozorováno": d.observed,
                "Očekávání": d.expected,
                "Rozdíl (dny)": d.residual,
                "Relativní rozdíl": (np.expm1(d.log_residual) if pd.notna(d.log_residual) else np.nan),
                "Standardizovaná odchylka": d.z,
                "Rozhoduje o označení": "ano" if (bool(score_row["scored"]) and d.is_driver) else "",
                "Pobytů ve výpočtu": d.support_n,
            }
        )
    table = pd.DataFrame(rows)

    if not bool(score_row["scored"]):
        summary = f"Případ není v tomto pohledu skórován: {score_row['not_scored_reason']}"
        return {"summary": summary, "table": table, "counterfactual": ""}

    drv = dims_rows[dims_rows["metric_id"] == score_row["driver_metric"]].iloc[0]
    label = metric_labels.get(drv["metric_id"], drv["metric_id"])
    scale_txt = "v logaritmické (relativní) škále" if config.scale == "log" else "v dnech"
    support_n = int(drv["support_n"])
    summary = (
        f"{label} je {fmt_days(drv['observed'])}, referenční očekávání {fmt_days(drv['expected'])}. "
        f"Rozdíl je {fmt_signed_days(drv['residual'])} ({DIRECTION_LABELS[score_row['direction']]}). "
        f"Standardizovaná odchylka {fmt_num(drv['z'], 2)} ({scale_txt}, vůči lokální referenci) "
        f"{'překračuje' if score_row['outlier'] else 'nepřekračuje'} pracovní práh {fmt_num(config.threshold)}. "
        f"Počet pobytů ve výpočtu pacienta: {support_n}."
    )
    if len(dims_rows) > 1:
        summary += (
            " Celkové skóre je maximum přes zvolené ukazatele (ne součet) – o označení rozhoduje "
            "ukazatel s největší odchylkou."
        )
    if score_row["support_notes"]:
        summary += f" ⚠ Omezená opora dat: {score_row['support_notes']}."
    summary += f" Citlivost na volbě prahu: {score_row['sensitivity']}."

    cf_parts = []
    for d in dims_rows.itertuples(index=False):
        if d.standardizable and pd.notna(d.allowed_low):
            cf_parts.append(
                f"{metric_labels.get(d.metric_id, d.metric_id).lower()} {fmt_num(d.allowed_low)}–"
                f"{fmt_num(d.allowed_high)} dní"
            )
    counterfactual = ""
    if cf_parts:
        lead = (
            f"Při prahu {fmt_num(config.threshold)} by pacient nebyl označen, kdyby pozorované hodnoty ležely v rozmezí: "
            if score_row["outlier"]
            else f"Při prahu {fmt_num(config.threshold)} by pacient byl označen, kdyby některá hodnota ležela mimo rozmezí: "
        )
        counterfactual = lead + "; ".join(cf_parts) + ". Jde o vlastnost skóre, ne o léčebné doporučení."
    return {"summary": summary, "table": table, "counterfactual": counterfactual}


# ---------------------------------------------------------------------------
# C. Čím se pacient liší od srovnávaných?
# ---------------------------------------------------------------------------


def _is_missing_value(v) -> bool:
    return (
        v is None or (isinstance(v, float) and np.isnan(v)) or (isinstance(v, str) and v == "") or v is pd.NA
    )


def _cat_value(v) -> str:
    if _is_missing_value(v):
        return "chybí"
    if isinstance(v, (bool, np.bool_)):
        return "ano" if v else "ne"
    return str(v)


def explain_differences(
    pid: str,
    comparison_ids: list[str],
    table: pd.DataFrame,
    cat_cols: list[str],
    num_cols: list[str],
    label_fn: LabelFn,
) -> pd.DataFrame:
    """Srovnání charakteristik pacienta se srovnávací množinou (deskriptivně)."""
    t = table.set_index("patient_id")
    me = t.loc[pid]
    comp = t.loc[[c for c in comparison_ids if c in t.index and c != pid]]
    rows = []
    for col in cat_cols:
        if col not in t.columns:
            continue
        mine = _cat_value(me[col])
        vals = comp[col].map(_cat_value)
        avail = vals[vals != "chybí"]
        n = len(avail)
        same = int((avail == mine).sum()) if mine != "chybí" else 0
        share = same / n if n else np.nan
        mode = avail.value_counts().index[0] if n else "–"
        mode_share = avail.value_counts().iloc[0] / n if n else np.nan
        unusual = (1 - share) if (mine != "chybí" and n >= 3) else 0.0
        rows.append(
            {
                "Charakteristika": label_fn(col),
                "Pacient": mine,
                "Srovnávaní pacienti": (
                    f"stejnou hodnotu má {same} z {n} ({fmt_pct(share)}); nejčastěji {mode} "
                    f"({fmt_pct(mode_share)})"
                    if n
                    else "údaj u srovnávaných chybí"
                ),
                "Dostupné n": n,
                "Neobvyklost": unusual,
            }
        )
    for col in num_cols:
        if col not in t.columns:
            continue
        x = pd.to_numeric(pd.Series([me[col]]), errors="coerce").iloc[0]
        vals = pd.to_numeric(comp[col], errors="coerce").dropna().astype(float)
        n = len(vals)
        if n == 0:
            desc = "údaj u srovnávaných chybí"
            unusual = 0.0
        else:
            q1, med, q3 = vals.quantile([0.25, 0.5, 0.75])
            desc = f"medián {fmt_num(med)} (kvartily {fmt_num(q1)}–{fmt_num(q3)})"
            if pd.notna(x):
                pct = (float((vals < x).sum()) + 0.5 * float((vals == x).sum())) / n
                desc += f"; pacient je na {fmt_num(100 * pct, 0)}. percentilu"
                unusual = abs(pct - 0.5) * 2 if n >= 3 else 0.0
            else:
                unusual = 0.0
        rows.append(
            {
                "Charakteristika": label_fn(col),
                "Pacient": fmt_num(x) if pd.notna(x) else "chybí",
                "Srovnávaní pacienti": desc,
                "Dostupné n": n,
                "Neobvyklost": unusual,
            }
        )
    out = pd.DataFrame(
        rows, columns=["Charakteristika", "Pacient", "Srovnávaní pacienti", "Dostupné n", "Neobvyklost"]
    )
    return out.sort_values("Neobvyklost", ascending=False, kind="stable").reset_index(drop=True)


# ---------------------------------------------------------------------------
# Skupinové vysvětlení
# ---------------------------------------------------------------------------

GROUP_SUMMARY_COLUMNS = [
    "group",
    "comparison_set",
    "feature",
    "feature_label",
    "kind",
    "value",
    "group_stat",
    "reference_stat",
    "difference",
    "n_group_available",
    "n_reference_available",
    "text",
]


def _compare_categorical(members, ref, t, col, label, group_name, comp_name) -> list[dict]:
    g = t.loc[members, col].map(_cat_value)
    r = t.loc[ref, col].map(_cat_value)
    g_av, r_av = g[g != "chybí"], r[r != "chybí"]
    rows = []
    for value, cnt in g_av.value_counts().items():
        share_g = cnt / len(g_av)
        share_r = (r_av == value).sum() / len(r_av) if len(r_av) else np.nan
        diff = share_g - share_r if pd.notna(share_r) else np.nan
        rows.append(
            {
                "group": group_name,
                "comparison_set": comp_name,
                "feature": col,
                "feature_label": label,
                "kind": "categorical",
                "value": value,
                "group_stat": share_g,
                "reference_stat": share_r,
                "difference": diff,
                "n_group_available": len(g_av),
                "n_reference_available": len(r_av),
                "text": (
                    f"{label} = {value}: {cnt}/{len(g_av)} ve skupině ({fmt_pct(share_g)}) vs. "
                    f"{fmt_pct(share_r)} v referenci (n={len(r_av)}); rozdíl {fmt_pp(diff)}"
                ),
                "_count": int(cnt),
            }
        )
    missing_g = int((g == "chybí").sum())
    if missing_g and len(members):
        rows.append(
            {
                "group": group_name,
                "comparison_set": comp_name,
                "feature": col,
                "feature_label": label,
                "kind": "missing",
                "value": "chybí",
                "group_stat": missing_g / len(members),
                "reference_stat": (r == "chybí").mean() if len(r) else np.nan,
                "difference": np.nan,
                "n_group_available": len(g_av),
                "n_reference_available": len(r_av),
                "text": f"{label}: údaj chybí u {missing_g}/{len(members)} pacientů skupiny",
                "_count": 0,
            }
        )
    return rows


def _compare_numeric(members, ref, t, col, label, group_name, comp_name) -> dict | None:
    g = pd.to_numeric(t.loc[members, col], errors="coerce").dropna().astype(float)
    r = pd.to_numeric(t.loc[ref, col], errors="coerce").dropna().astype(float)
    if len(g) == 0:
        return None
    gq = g.quantile([0.25, 0.5, 0.75])
    rq = r.quantile([0.25, 0.5, 0.75]) if len(r) else pd.Series([np.nan] * 3, index=[0.25, 0.5, 0.75])
    iqr = rq[0.75] - rq[0.25]
    denom = (
        iqr if pd.notna(iqr) and iqr > 0 else (abs(rq[0.5]) if pd.notna(rq[0.5]) and rq[0.5] != 0 else 1.0)
    )
    std_diff = (gq[0.5] - rq[0.5]) / denom if pd.notna(rq[0.5]) else np.nan
    return {
        "group": group_name,
        "comparison_set": comp_name,
        "feature": col,
        "feature_label": label,
        "kind": "numeric",
        "value": "",
        "group_stat": gq[0.5],
        "reference_stat": rq[0.5],
        "difference": gq[0.5] - rq[0.5] if pd.notna(rq[0.5]) else np.nan,
        "n_group_available": len(g),
        "n_reference_available": len(r),
        "text": (
            f"{label}: medián {fmt_num(gq[0.5])} (IQR {fmt_num(gq[0.25])}–{fmt_num(gq[0.75])}, n={len(g)}) "
            f"vs. {fmt_num(rq[0.5])} (IQR {fmt_num(rq[0.25])}–{fmt_num(rq[0.75])}, n={len(r)})"
        ),
        "_std": abs(std_diff) if pd.notna(std_diff) else 0.0,
    }


def _compare_labs(members, ref, lab_medians, group_name, comp_name) -> list[dict]:
    rows = []
    if lab_medians is None or lab_medians.empty:
        return rows
    lm = lab_medians[lab_medians["patient_id"].isin(set(members) | set(ref))]
    for key, sub in lm.groupby("test_key"):
        g = sub[sub["patient_id"].isin(members)]["median_value"]
        r = sub[sub["patient_id"].isin(ref)]["median_value"]
        if len(g) < 2 or len(r) < 3:
            continue
        label = f"Laboratoř {sub['test_label'].iloc[0]} (medián na pacienta)"
        iqr = r.quantile(0.75) - r.quantile(0.25)
        std = abs(g.median() - r.median()) / iqr if iqr > 0 else 0.0
        rows.append(
            {
                "group": group_name,
                "comparison_set": comp_name,
                "feature": f"lab:{key}",
                "feature_label": label,
                "kind": "lab",
                "value": "",
                "group_stat": g.median(),
                "reference_stat": r.median(),
                "difference": g.median() - r.median(),
                "n_group_available": len(g),
                "n_reference_available": len(r),
                "text": (
                    f"{label}: {fmt_num(g.median(), 2)} (n={len(g)}) vs. {fmt_num(r.median(), 2)} (n={len(r)}); "
                    "meze mohou být dospělé"
                ),
                "_std": std,
            }
        )
    return rows


def _comparisons(members, ref, t, cat_cols, num_cols, lab_medians, label_fn, group_name, comp_name):
    rows: list[dict] = []
    for col in cat_cols:
        if col in t.columns:
            rows.extend(_compare_categorical(members, ref, t, col, label_fn(col), group_name, comp_name))
    for col in num_cols:
        if col in t.columns:
            r = _compare_numeric(members, ref, t, col, label_fn(col), group_name, comp_name)
            if r:
                rows.append(r)
    rows.extend(_compare_labs(members, ref, lab_medians, group_name, comp_name))
    return rows


def _top_findings(rows: list[dict], k: int = 6) -> list[str]:
    cat = [
        r
        for r in rows
        if r["kind"] == "categorical"
        and r["_count"] >= 2
        and pd.notna(r["difference"])
        and abs(r["difference"]) >= 0.2
    ]
    cat.sort(key=lambda r: -abs(r["difference"]))
    num = [
        r
        for r in rows
        if r["kind"] in ("numeric", "lab")
        and r["n_group_available"] >= 2
        and r["n_reference_available"] >= 3
        and r["_std"] >= 0.5
    ]
    num.sort(key=lambda r: -r["_std"])
    merged = []
    for a, b in zip(cat, num, strict=False):
        merged.extend([a, b])
    longer, shorter = (cat, num) if len(cat) > len(num) else (num, cat)
    merged.extend(longer[len(shorter) :])
    return [r["text"] for r in merged[:k]]


def describe_groups(
    clusters: pd.DataFrame,
    scores: pd.DataFrame,
    dims: pd.DataFrame,
    table: pd.DataFrame,
    reference_ids: tuple[str, ...],
    cat_cols: list[str],
    num_cols: list[str],
    lab_medians: pd.DataFrame | None,
    label_fn: LabelFn,
    metric_labels: dict[str, str],
) -> tuple[pd.DataFrame, list[dict]]:
    t = table.set_index("patient_id")
    all_rows: list[dict] = []
    cards: list[dict] = []
    if clusters.empty:
        return pd.DataFrame(columns=GROUP_SUMMARY_COLUMNS), cards
    grouped = clusters[~clusters["isolated"].astype(bool)]
    for cid, sub in grouped.groupby("cluster_id"):
        members = sorted(sub["patient_id"])
        name = f"Skupina {int(cid)}"
        ref = [p for p in reference_ids if p not in members]
        dx_set = set(t.loc[members, "dx_icd10"])
        dx_ref = [p for p in ref if t.at[p, "dx_icd10"] in dx_set]

        # Profil reziduí
        prof_lines = []
        d = dims[dims["patient_id"].isin(members)]
        for m, dm in d.groupby("metric_id", sort=False):
            n_long = int((dm["residual"] > 0).sum())
            n_short = int((dm["residual"] < 0).sum())
            prof_lines.append(
                f"{metric_labels.get(m, m)}: medián pozorováno {fmt_days(dm['observed'].median())} vs. očekávání "
                f"{fmt_days(dm['expected'].median())}, medián standardizované odchylky {fmt_signed(dm['z'].median(), 2)}; "
                f"delší {n_long}×, kratší {n_short}×"
            )
        dx_comp = t.loc[members, "dx_icd10"].value_counts()
        rows_local = _comparisons(
            members, ref, t, cat_cols, num_cols, lab_medians, label_fn, name, "lokální reference"
        )
        rows_dx = _comparisons(
            members,
            dx_ref,
            t,
            cat_cols,
            num_cols,
            lab_medians,
            label_fn,
            name,
            "reference se stejnými diagnózami",
        )
        all_rows.extend(rows_local + rows_dx)

        warnings = []
        ref_dx_share = float(t.loc[ref, "dx_icd10"].isin(dx_set).mean()) if ref else 0.0
        if ref_dx_share < 0.3:
            warnings.append(
                f"Diagnózy skupiny ({', '.join(sorted(dx_set))}) tvoří jen {fmt_pct(ref_dx_share)} lokální reference – "
                "nalezený vzorec může odrážet odlišnou skladbu diagnóz."
            )
        if len(dx_ref) < 3:
            warnings.append(
                f"Reference se stejnými diagnózami má jen {len(dx_ref)} pacientů – srovnání je nestabilní."
            )
        if len(members) < 5:
            warnings.append("Malá skupina – popis je hypotéza pro mentora, ne statistický závěr.")

        cards.append(
            {
                "group": name,
                "cluster_id": int(cid),
                "members": members,
                "n": len(members),
                "profile": prof_lines,
                "dx_composition": ", ".join(f"{k} ({v})" for k, v in dx_comp.items()),
                "age_composition": ", ".join(
                    f"{k} ({v})" for k, v in t.loc[members, "age_group"].value_counts().items()
                ),
                "sex_composition": ", ".join(
                    f"{k} ({v})" for k, v in t.loc[members, "sex"].value_counts().items()
                ),
                "n_reference": len(ref),
                "n_dx_reference": len(dx_ref),
                "top_local": _top_findings(rows_local),
                "top_dx": _top_findings(rows_dx),
                "warnings": warnings,
            }
        )
    summary = pd.DataFrame(all_rows)
    summary = summary.drop(columns=[c for c in ("_count", "_std") if c in summary.columns])
    return summary.reindex(columns=GROUP_SUMMARY_COLUMNS), cards
