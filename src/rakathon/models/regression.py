"""Ridge regrese nad log1p délky pobytu s leave-one-patient-out (volitelná druhá baseline).

Vstupy: diagnostická kategorie (orientační skupina, u nezařazených diagnóz přesný kód), věková skupina,
pohlaví. Pro každého pacienta se encoder i model fitují jen na OSTATNÍCH pacientech (LOO), takže očekávání
nezávisí na jeho vlastním výsledku. Rozklad predikce (základ + příspěvky faktorů) pochází z TÉHOŽ LOO
fitu, který vydal očekávání.

Škála: model předpovídá log1p(délka). expm1(predikce) je „modelové typické očekávání“ (blíží se
geometrickému průměru 1 + délka), nikoli aritmetický průměr v dnech. Záporná predikce v log škále by
znamenala očekávání < 0 dní – pak se ořízne na 0 a uvede v detailu (netestovaný fallback se nepoužívá).
"""

from __future__ import annotations

import json

import numpy as np
import pandas as pd
from sklearn.linear_model import Ridge
from sklearn.preprocessing import OneHotEncoder

from rakathon.domain import BaselineConfig, BaselineStatus
from rakathon.models.base import BASELINE_OUTPUT_COLUMNS

FEATURES = ("dx_cat", "age_group", "sex")
FEATURE_LABELS = {"dx_cat": "diagnostická kategorie", "age_group": "věková skupina", "sex": "pohlaví"}


def diagnosis_category(core: pd.DataFrame) -> tuple[pd.Series, pd.Series]:
    """(kategorie, popisek): orientační skupina, nebo přesný kód u nezařazených diagnóz."""
    cat = np.where(core["dx_group"] != "", core["dx_group"], "dx:" + core["dx_icd10"])
    label = np.where(
        core["dx_group"] != "", core["dx_group_label"], core["dx_icd10"] + " (nezařazeno do skupiny)"
    )
    return pd.Series(cat, index=core.index), pd.Series(label, index=core.index)


class RidgeLooBaseline:
    method_id = "ridge_loo"
    label = "Ridge regrese nad log1p délky (diagnostická kategorie, věk, pohlaví), leave-one-patient-out"

    def predict(
        self, core: pd.DataFrame, outcomes_long: pd.DataFrame, config: BaselineConfig
    ) -> pd.DataFrame:
        excluded = set(config.excluded_patient_ids)
        core = core.set_index("patient_id")
        cat, cat_label = diagnosis_category(core)
        X = pd.DataFrame(
            {"dx_cat": cat, "age_group": core["age_group"], "sex": core["sex"]}, index=core.index
        )
        rows: list[dict] = []
        for metric in config.outcomes:
            obs = outcomes_long[outcomes_long["metric_id"] == metric].set_index("patient_id")["observed"]
            obs = obs.reindex(core.index)
            usable = obs.notna() & ~core["multi_tumor"] & ~core.index.isin(excluded)
            pool = obs[usable].astype(float)
            for pid in core.index:
                rows.append(self._predict_one(pid, metric, core, X, cat_label, pool, config, excluded))
        return pd.DataFrame(rows, columns=BASELINE_OUTPUT_COLUMNS)

    def _predict_one(self, pid, metric, core, X, cat_label, pool, config, excluded) -> dict:
        base = {"patient_id": pid, "metric_id": metric}
        train = pool.drop(index=pid, errors="ignore")
        population_median = float(train.median()) if len(train) else np.nan
        if bool(core.at[pid, "multi_tumor"]) or pid in excluded:
            reason = (
                "Vyřazen uživatelem z výpočtu: "
                + dict(config.exclusion_reasons).get(pid, "bez uvedeného důvodu")
                if pid in excluded
                else "Více nádorových řádků – přiřazení epizod není určeno."
            )
            return _empty(base, BaselineStatus.EXCLUDED, reason, population_median)
        my_cat = X.at[pid, "dx_cat"]
        same_cat = [q for q in train.index if X.at[q, "dx_cat"] == my_cat]
        k = len(same_cat)
        if k < config.min_limited_reference:
            reason = (
                f"Diagnostická kategorie {cat_label[pid]} má v trénovacích datech jen {k} jiných pacientů "
                f"s výsledkem (potřeba alespoň {config.min_limited_reference}) – model by vycházel jen z věku a "
                "pohlaví, proto se očekávání nevydává."
            )
            return _empty(base, BaselineStatus.INSUFFICIENT, reason, population_median)

        # LOO: encoder i model se fitují jen na ostatních pacientech.
        enc = OneHotEncoder(handle_unknown="ignore", sparse_output=False)
        Xt = enc.fit_transform(X.loc[train.index, list(FEATURES)])
        y = np.log1p(train.to_numpy())
        model = Ridge(alpha=config.ridge_alpha).fit(Xt, y)
        xi = enc.transform(X.loc[[pid], list(FEATURES)])[0]
        pred_log = float(model.intercept_ + xi @ model.coef_)
        names = enc.get_feature_names_out(list(FEATURES))
        terms = []
        for f in FEATURES:
            idx = [j for j, n in enumerate(names) if n.startswith(f + "_") and xi[j] == 1.0]
            value = X.at[pid, f]
            contribution = float(sum(model.coef_[j] for j in idx))
            terms.append(
                {
                    "factor": FEATURE_LABELS[f],
                    "value": cat_label[pid] if f == "dx_cat" else str(value),
                    "seen_in_training": bool(idx),
                    "contribution": contribution,
                }
            )
        clipped = pred_log < 0
        expected = 0.0 if clipped else float(np.expm1(pred_log))
        status = BaselineStatus.OK if k >= config.min_reference else BaselineStatus.LIMITED
        reason = ""
        if status == BaselineStatus.LIMITED:
            reason = (
                f"Omezená opora modelu: v diagnostické kategorii jen {k} jiných pacientů "
                f"(plná opora vyžaduje {config.min_reference})."
            )
        unseen = [t["factor"] for t in terms if not t["seen_in_training"]]
        if unseen:
            reason += f" Hodnota faktoru ({', '.join(unseen)}) se v trénovacích datech nevyskytla – nulový příspěvek."
        if clipped:
            reason += " Predikce v log škále byla záporná – očekávání oříznuto na 0 dní."
        detail = {
            "method": self.method_id,
            "scale": "log1p(dny)",
            "alpha": config.ridge_alpha,
            "train_n": int(len(train)),
            "category_n": k,
            "intercept": float(model.intercept_),
            "terms": terms,
            "pred_log": pred_log,
            "clipped": bool(clipped),
        }
        values = pool.loc[same_cat]
        factors_not = "přesná diagnóza (jen orientační skupina)" if core.at[pid, "dx_group"] else ""
        return {
            **base,
            "expected": expected,
            "baseline_status": status.value,
            "baseline_reason": reason.strip(),
            "reference_level": pd.NA,
            "reference_level_label": "model Ridge (LOO); srovnávací pacienti = stejná diagnostická kategorie",
            "factors_used": "; ".join(f"{t['factor']} {t['value']}" for t in terms),
            "factors_not_used": factors_not,
            "reference_n": k,
            "reference_ids": ";".join(sorted(same_cat)),
            "ref_q1": float(values.quantile(0.25)),
            "ref_q3": float(values.quantile(0.75)),
            "ref_min": float(values.min()),
            "ref_max": float(values.max()),
            "population_median": population_median,
            "model_detail": json.dumps(detail, ensure_ascii=False),
        }


def _empty(base: dict, status: BaselineStatus, reason: str, population_median: float) -> dict:
    return {
        **base,
        "expected": np.nan,
        "baseline_status": status.value,
        "baseline_reason": reason,
        "reference_level": pd.NA,
        "reference_level_label": "",
        "factors_used": "",
        "factors_not_used": "",
        "reference_n": 0,
        "reference_ids": "",
        "ref_q1": np.nan,
        "ref_q3": np.nan,
        "ref_min": np.nan,
        "ref_max": np.nan,
        "population_median": population_median,
        "model_detail": "",
    }
