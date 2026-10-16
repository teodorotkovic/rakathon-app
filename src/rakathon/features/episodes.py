"""Výběr epizod pro výsledkové ukazatele a epizodní kontext pacienta.

Pravidla:
- délka pobytu = day_end − day_start (bez +1), jen dokončené hospitalizace;
- žádný vybraný pobyt → chybějící výsledek s důvodem, nikdy 0;
- den 0 je první záznam v nemocnici, ne diagnóza ani začátek léčby;
- pacient s více nádory se z výsledků vyřazuje (přiřazení epizod není určeno).
"""

from __future__ import annotations

import numpy as np
import pandas as pd

from rakathon.configuration import DiagnosisMap
from rakathon.domain import EpisodeClass, OutcomeStatus

SELECTED_COLUMNS = ["patient_id", "episode_id", "seq", "day_start_num", "day_end_num", "los_days", "dx_main"]


def find_anchors(episodes: pd.DataFrame, core: pd.DataFrame) -> pd.DataFrame:
    """Kotva = první epizoda (podle seq) s dx_main shodnou s diagnózou nádoru. Proxy, ne datum diagnózy."""
    e = episodes[episodes["known_patient"] & (episodes["episode_class"] != EpisodeClass.INVALID.value)]
    m = e.merge(core.loc[~core["multi_tumor"], ["patient_id", "dx_icd10"]], on="patient_id")
    m = m[(m["dx_main"] != "") & (m["dx_main"] == m["dx_icd10"])].sort_values(["patient_id", "seq"])
    first = m.drop_duplicates("patient_id", keep="first")
    return first.rename(
        columns={"seq": "anchor_seq", "day_start_num": "anchor_day", "episode_id": "anchor_episode_id"}
    )[["patient_id", "anchor_seq", "anchor_day", "anchor_episode_id"]]


def select_outcome_episodes(
    episodes: pd.DataFrame, core: pd.DataFrame, rule: str, dxmap: DiagnosisMap
) -> pd.DataFrame:
    """Vrátí dokončené hospitalizace, které vstupují do výsledkového ukazatele."""
    inp = episodes[episodes["known_patient"] & (episodes["episode_class"] == EpisodeClass.INPATIENT.value)]
    single = core.loc[~core["multi_tumor"], ["patient_id", "dx_icd10", "dx_group"]]
    m = inp.merge(single, on="patient_id", how="inner", validate="many_to_one")
    if rule == "exact_dx_match":
        sel = m[(m["dx_main"] != "") & (m["dx_main"] == m["dx_icd10"])]
    elif rule == "group_dx_match":
        main_group = m["dx_main"].map(lambda c: dxmap.group_of(c) or "")
        same_group = (m["dx_group"] != "") & (main_group == m["dx_group"])
        sel = m[((m["dx_main"] != "") & (m["dx_main"] == m["dx_icd10"])) | same_group]
    elif rule == "from_anchor_all_inpatient":
        anchors = find_anchors(episodes, core)
        m = m.merge(
            anchors[["patient_id", "anchor_seq"]], on="patient_id", how="inner", validate="many_to_one"
        )
        sel = m[m["seq"] >= m["anchor_seq"]]
    else:
        raise ValueError(f"Neznámé pravidlo výběru epizod: {rule}")
    return sel[SELECTED_COLUMNS].sort_values(["patient_id", "seq"]).reset_index(drop=True)


def compute_outcomes(
    selected: pd.DataFrame,
    core: pd.DataFrame,
    rule: str,
    anchors: pd.DataFrame | None = None,
    metrics: tuple[str, ...] = ("median_los_dx", "max_los_dx"),
) -> pd.DataFrame:
    """Long tabulka pacient × ukazatel: observed, support_n, outcome_status, outcome_reason."""
    agg = selected.groupby("patient_id")["los_days"].agg(n="size", median="median", max="max")
    has_anchor = set(anchors["patient_id"]) if anchors is not None else set()
    rows = []
    for r in core.itertuples(index=False):
        pid = r.patient_id
        n = int(agg.at[pid, "n"]) if pid in agg.index else 0
        if r.multi_tumor:
            status, reason = (
                OutcomeStatus.EXCLUDED,
                ("Pacient má více nádorových řádků; přiřazení epizod k nádorům není určeno."),
            )
        elif r.dx_icd10 == "":
            status, reason = OutcomeStatus.NO_STAY, "Chybí diagnóza nádoru – nelze vybrat pobyty."
        elif rule == "from_anchor_all_inpatient" and pid not in has_anchor:
            status, reason = (
                OutcomeStatus.NO_ANCHOR,
                ("Žádná epizoda s diagnózou nádoru – chybí kotva; výpočet nezačíná skrytě od dne 0."),
            )
        elif n == 0:
            status, reason = OutcomeStatus.NO_STAY, "Žádná dokončená hospitalizace splňující pravidlo výběru."
        elif n == 1:
            status, reason = OutcomeStatus.SINGLE_STAY, "Hodnota vychází z jediného pobytu – omezená opora."
        else:
            status, reason = OutcomeStatus.OK, ""
        for metric in metrics:
            if status in (OutcomeStatus.OK, OutcomeStatus.SINGLE_STAY):
                stat = "median" if metric == "median_los_dx" else "max"
                observed = float(agg.at[pid, stat])
            else:
                observed = np.nan
            rows.append(
                {
                    "patient_id": pid,
                    "metric_id": metric,
                    "observed": observed,
                    "support_n": n if status != OutcomeStatus.EXCLUDED else 0,
                    "outcome_status": status.value,
                    "outcome_reason": reason,
                }
            )
    return pd.DataFrame(rows)


def episode_context(
    episodes: pd.DataFrame, core: pd.DataFrame, selected: pd.DataFrame, anchors: pd.DataFrame
) -> pd.DataFrame:
    """Kontextové počty na pacienta. Nejsou skórovanými výsledky (chybí srovnatelná doba pozorování)."""
    e = episodes[episodes["known_patient"]]
    cls = e["episode_class"]
    g = e.assign(
        is_out=cls == EpisodeClass.OUTPATIENT.value,
        is_inp=cls == EpisodeClass.INPATIENT.value,
        is_open=cls == EpisodeClass.OPEN.value,
        is_invalid=cls == EpisodeClass.INVALID.value,
        is_d70=e["dx_main"] == "D70",
        dx_missing=e["dx_main"] == "",
        last_day=np.fmax(e["day_start_num"].astype(float), e["day_end_num"].astype(float)),
    ).groupby("patient_id")
    ctx = pd.DataFrame(
        {
            "n_episodes": g.size(),
            "n_outpatient": g["is_out"].sum(),
            "n_inpatient_completed": g["is_inp"].sum(),
            "n_inpatient_open": g["is_open"].sum(),
            "n_invalid_intervals": g["is_invalid"].sum(),
            "n_d70_episodes": g["is_d70"].sum(),
            "n_dx_missing": g["dx_missing"].sum(),
            "history_span_days": g["last_day"].max(),
        }
    )
    first = e.sort_values(["patient_id", "seq"]).drop_duplicates("patient_id")
    ctx["first_episode_birth"] = first.set_index("patient_id")["dx_main"].eq("Z38")
    ctx["n_stays_included"] = selected.groupby("patient_id").size()
    open_dx = e[e["episode_class"] == EpisodeClass.OPEN.value].merge(
        core[["patient_id", "dx_icd10"]], on="patient_id"
    )
    ctx["n_open_matching_dx"] = (
        open_dx[open_dx["dx_main"] == open_dx["dx_icd10"]].groupby("patient_id").size()
    )
    ctx = ctx.reindex(core["patient_id"])
    count_cols = [
        "n_episodes",
        "n_outpatient",
        "n_inpatient_completed",
        "n_inpatient_open",
        "n_invalid_intervals",
        "n_d70_episodes",
        "n_dx_missing",
        "n_stays_included",
        "n_open_matching_dx",
    ]
    ctx[count_cols] = ctx[count_cols].fillna(0).astype(int)
    ctx["first_episode_birth"] = ctx["first_episode_birth"].fillna(False).astype(bool)
    ctx.index.name = "patient_id"
    ctx = ctx.reset_index().merge(
        anchors[["patient_id", "anchor_day", "anchor_episode_id"]],
        on="patient_id",
        how="left",
        validate="one_to_one",
    )
    ctx["anchor_episode_id"] = ctx["anchor_episode_id"].fillna("")
    return ctx
