"""Referenční medián podobných pacientů (PeerMedianBaseline) s leave-one-patient-out.

Pro každého pacienta se prochází předem daná hierarchie reference (např. stejná
diagnóza + věk + pohlaví → … → orientační skupina). Zvolí se první úroveň, kde je
alespoň `min_reference` JINÝCH pacientů s dostupným cílem. Pokud žádná, použije se
první úroveň s alespoň `min_limited_reference` (omezená reference). Jinak se
očekávání nevydá („nedostatek srovnatelných případů“).

Očekávání = medián pacientských hodnot reference; každý pacient má jeden hlas.
Hodnocený pacient se na vlastním očekávání nepodílí.
"""

from __future__ import annotations

import numpy as np
import pandas as pd

from rakathon.domain import BaselineConfig, BaselineStatus
from rakathon.models.base import BASELINE_OUTPUT_COLUMNS

FACTOR_LABELS = {
    "dx_icd10": "diagnóza",
    "dx_group": "orientační diagnostická skupina",
    "age_group": "věková skupina",
    "sex": "pohlaví",
}
# Faktory, které by „ideální“ reference zohlednila. Pokud je úroveň nepoužívá, uvede se to.
FULL_FACTORS = ("dx_icd10", "age_group", "sex")


def level_label(keys: tuple[str, ...]) -> str:
    return "stejná " + ", ".join(FACTOR_LABELS[k] for k in keys)


def factors_not_used(keys: tuple[str, ...]) -> list[str]:
    missing = []
    for f in FULL_FACTORS:
        if f in keys:
            continue
        if f == "dx_icd10" and "dx_group" in keys:
            missing.append("přesná diagnóza (jen orientační skupina)")
        else:
            missing.append(FACTOR_LABELS[f])
    return missing


class PeerMedianBaseline:
    method_id = "peer_median"
    label = "Referenční medián podobných pacientů (leave-one-patient-out)"

    def predict(
        self, core: pd.DataFrame, outcomes_long: pd.DataFrame, config: BaselineConfig
    ) -> pd.DataFrame:
        excluded = set(config.excluded_patient_ids)
        rows: list[dict] = []
        core = core.set_index("patient_id")
        for metric in config.outcomes:
            obs = outcomes_long[outcomes_long["metric_id"] == metric].set_index("patient_id")["observed"]
            obs = obs.reindex(core.index)
            usable = obs.notna() & ~core["multi_tumor"] & ~core.index.isin(excluded)
            pool = obs[usable]
            # Pro každou úroveň: klíč pacienta (nebo None, pokud faktor chybí) a skupiny použitelných pacientů.
            level_keys: list[pd.Series] = []
            level_groups: list[dict] = []
            for keys in config.hierarchy:
                key = core[list(keys)].apply(
                    lambda r: None if any(v == "" or pd.isna(v) for v in r) else tuple(r), axis=1
                )
                level_keys.append(key)
                groups: dict[tuple, list[str]] = {}
                for pid in pool.index:
                    k = key.at[pid]
                    if k is not None:
                        groups.setdefault(k, []).append(pid)
                level_groups.append(groups)

            for pid in core.index:
                rows.append(
                    self._predict_one(pid, metric, core, pool, level_keys, level_groups, config, excluded)
                )
        return pd.DataFrame(rows, columns=BASELINE_OUTPUT_COLUMNS)

    def _predict_one(self, pid, metric, core, pool, level_keys, level_groups, config, excluded) -> dict:
        base = {"patient_id": pid, "metric_id": metric}
        others = pool.drop(index=pid, errors="ignore")
        population_median = float(others.median()) if len(others) else np.nan
        if bool(core.at[pid, "multi_tumor"]) or pid in excluded:
            reason = (
                "Vyřazen uživatelem z výpočtu: "
                + dict(config.exclusion_reasons).get(pid, "bez uvedeného důvodu")
                if pid in excluded
                else "Více nádorových řádků – přiřazení epizod není určeno."
            )
            return self._empty(base, BaselineStatus.EXCLUDED, reason, population_median)

        chosen = None
        limited = None
        best_n = 0
        skipped: list[str] = []
        for i, keys in enumerate(config.hierarchy):
            k = level_keys[i].at[pid]
            if k is None:
                skipped.append(level_label(keys) + " (údaj chybí / diagnóza nezařazena)")
                continue
            peers = [q for q in level_groups[i].get(k, []) if q != pid]
            n = len(peers)
            best_n = max(best_n, n)
            if n >= config.min_reference:
                chosen = (i, keys, peers, BaselineStatus.OK)
                break
            if limited is None and n >= config.min_limited_reference:
                limited = (i, keys, peers, BaselineStatus.LIMITED)
        if chosen is None:
            chosen = limited
        if chosen is None:
            reason = (
                f"Nedostatek srovnatelných případů: nejvýše {best_n} jiných pacientů s dostupným výsledkem "
                f"(potřeba alespoň {config.min_limited_reference})."
            )
            if skipped:
                reason += " Nepoužitelné úrovně: " + "; ".join(skipped) + "."
            return self._empty(base, BaselineStatus.INSUFFICIENT, reason, population_median)

        i, keys, peers, status = chosen
        values = pool.loc[peers].astype(float)
        used = "; ".join(
            f"{FACTOR_LABELS[k]} {core.at[pid, k] if k != 'dx_group' else core.at[pid, 'dx_group_label']}"
            for k in keys
        )
        reason = ""
        if status == BaselineStatus.LIMITED:
            reason = (
                f"Omezená reference: jen {len(peers)} srovnatelných pacientů "
                f"(plná reference vyžaduje {config.min_reference})."
            )
        return {
            **base,
            "expected": float(np.median(values)),
            "baseline_status": status.value,
            "baseline_reason": reason,
            "reference_level": i + 1,
            "reference_level_label": level_label(keys),
            "factors_used": used,
            "factors_not_used": ", ".join(factors_not_used(keys)),
            "reference_n": len(peers),
            "reference_ids": ";".join(sorted(peers)),
            "ref_q1": float(values.quantile(0.25)),
            "ref_q3": float(values.quantile(0.75)),
            "ref_min": float(values.min()),
            "ref_max": float(values.max()),
            "population_median": population_median,
            "model_detail": "",
        }

    @staticmethod
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
