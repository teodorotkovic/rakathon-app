"""Podobní pacienti podle výchozích charakteristik (diagnóza/skupina, věk, pohlaví).

Posuzovaný výsledek NENÍ kritériem podobnosti. Každý podobný pacient nese
textový důvod podobnosti.
"""

from __future__ import annotations

import pandas as pd


def similar_patients(pid: str, core: pd.DataFrame, k: int = 8) -> pd.DataFrame:
    me = core.set_index("patient_id").loc[pid]
    rows = []
    for r in core.itertuples(index=False):
        if r.patient_id == pid:
            continue
        score = 0.0
        reasons = []
        if r.dx_icd10 and r.dx_icd10 == me["dx_icd10"]:
            score += 3
            reasons.append(f"stejná diagnóza {r.dx_icd10}")
        elif r.dx_group and r.dx_group == me["dx_group"]:
            score += 1.5
            reasons.append(f"stejná orientační skupina ({r.dx_group_label})")
        if r.age_group and r.age_group == me["age_group"]:
            score += 1
            reasons.append(f"stejná věková skupina {r.age_group}")
        elif (
            pd.notna(r.age_order)
            and pd.notna(me["age_order"])
            and abs(int(r.age_order) - int(me["age_order"])) == 1
        ):
            score += 0.5
            reasons.append(f"sousední věková skupina {r.age_group}")
        if r.sex and r.sex == me["sex"]:
            score += 0.5
            reasons.append("stejné pohlaví")
        if score >= 1.5:  # bez shody diagnózy/skupiny nebo věku+pohlaví nejde o smysluplnou podobnost
            rows.append(
                {
                    "patient_id": r.patient_id,
                    "similarity": score,
                    "reason": "; ".join(reasons),
                    "dx_icd10": r.dx_icd10,
                    "age_group": r.age_group,
                    "sex": r.sex,
                }
            )
    out = pd.DataFrame(rows, columns=["patient_id", "similarity", "reason", "dx_icd10", "age_group", "sex"])
    return (
        out.sort_values(["similarity", "patient_id"], ascending=[False, True]).head(k).reset_index(drop=True)
    )
