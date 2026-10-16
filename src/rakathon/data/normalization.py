"""Normalizace raw tabulek do typovaných tabulek s interpretovanými sloupci.

Raw hodnoty se zachovávají (sloupce s původním názvem jako text); interpretace
vzniká v nových sloupcích s příponou nebo popisným názvem. Nic se nedoplňuje
odhadem: neznámé kódy zůstávají neznámé.
"""

from __future__ import annotations

import numpy as np
import pandas as pd

from rakathon.configuration import DiagnosisMap
from rakathon.data.validation import (
    AGE_GROUPS,
    EPISODE_COLUMNS,
    INT_RE,
    LAB_COLUMNS,
    NUM_RE,
    PATIENT_COLUMNS,
)
from rakathon.domain import EpisodeClass


def _strip_all(df: pd.DataFrame, columns: list[str]) -> pd.DataFrame:
    out = df[columns].copy()
    for col in columns:
        out[col] = out[col].astype(str).str.strip()
    return out


def _to_int(series: pd.Series) -> pd.Series:
    ok = series.str.fullmatch(INT_RE).fillna(False).astype(bool)
    return pd.to_numeric(series.where(ok), errors="coerce").astype("Int64")


def _to_float(series: pd.Series) -> pd.Series:
    ok = series.str.fullmatch(NUM_RE).fillna(False).astype(bool)
    return pd.to_numeric(series.where(ok), errors="coerce").astype(float)


# ---------------------------------------------------------------------------
# Pacienti
# ---------------------------------------------------------------------------

STAGE_UNKNOWN = {"9", "X"}


def _stage_status(v: str) -> str:
    if v == "":
        return "chybí"
    if v == "9":
        return "neznámé (kód 9)"
    if v == "7":
        return "kód 7 – význam nepotvrzen"
    return "uvedeno"


def _grade_status(v: str) -> str:
    if v == "":
        return "chybí"
    if v == "9":
        return "neznámo (kód 9)"
    if v in {"1", "2", "3", "4"}:
        return "stupeň diferenciace (1–4)"
    if v in {"5", "6"}:
        return "kód buněčného typu (5/6)"
    return "neověřený kód"


def _morph_status(v: str) -> str:
    if v == "":
        return "chybí"
    if v == "3333/3":
        return "zástupná hodnota 3333/3 (neznámá)"
    if pd.Series([v]).str.fullmatch(r"[0-9]{4}/[0-9]").iloc[0]:
        return "platný formát"
    return "neplatný formát"


BEHAVIOUR_LABELS = {"/3": "maligní (/3)", "/1": "nejisté chování (/1)"}


def _behaviour(v: str) -> str:
    if v == "" or v == "3333/3" or "/" not in v:
        return ""
    return "/" + v.split("/")[-1]


def normalize_patients(raw: pd.DataFrame, dxmap: DiagnosisMap) -> pd.DataFrame:
    p = _strip_all(raw, PATIENT_COLUMNS)
    p["tumor_id_num"] = _to_int(p["tumor_id"])
    p["n_tumors"] = p.groupby("patient_id")["patient_id"].transform("size").astype(int)
    p["multi_tumor"] = p["n_tumors"] > 1
    p["dx_group"] = p["dx_icd10"].map(lambda c: dxmap.group_of(c) or "")
    p["dx_group_label"] = p["dx_group"].map(dxmap.label_of_group)
    p["age_order"] = p["age_group"].map({g: i for i, g in enumerate(AGE_GROUPS)}).astype("Int64")
    p["stage_status"] = p["stage"].map(_stage_status)
    p["stage_usable"] = p["stage_status"] == "uvedeno"
    p["grade_status"] = p["grade"].map(_grade_status)
    p["morphology_status"] = p["morphology_icdo3"].map(_morph_status)
    p["morphology_behaviour"] = p["morphology_icdo3"].map(_behaviour)
    p["morphology_behaviour_label"] = p["morphology_behaviour"].map(
        lambda b: BEHAVIOUR_LABELS.get(b, f"kód chování {b} (popis nepotvrzen v podkladech)" if b else "neznámé")
    )
    p["tnm_clinical_available"] = (p[["t", "n", "m"]] != "").any(axis=1)
    return p


def patient_core(patients_norm: pd.DataFrame) -> pd.DataFrame:
    """Jeden řádek na pacienta. U více nádorů se zobrazí první nádor a seznam všech diagnóz."""
    p = patients_norm.sort_values(["patient_id", "tumor_id_num"], na_position="last")
    dx_all = p.groupby("patient_id")["dx_icd10"].agg(lambda s: "; ".join(dict.fromkeys(s)))
    core = p.drop_duplicates("patient_id", keep="first").set_index("patient_id")
    core["dx_all"] = dx_all
    return core.reset_index()


# ---------------------------------------------------------------------------
# Epizody
# ---------------------------------------------------------------------------


def normalize_episodes(raw: pd.DataFrame, known_patients: set[str]) -> pd.DataFrame:
    e = _strip_all(raw, EPISODE_COLUMNS)
    e["day_start_num"] = _to_int(e["day_start"])
    e["day_end_num"] = _to_int(e["day_end"])
    e["seq"] = _to_int(e["episode_id"].str.extract(r"-E([0-9]+)$", expand=False).fillna(""))
    start = e["day_start_num"].astype(float)
    end = e["day_end_num"].astype(float)
    end_text_bad = (e["day_end"] != "") & e["day_end_num"].isna()
    cls = np.select(
        [end_text_bad | start.isna(), e["day_end"] == "", end < start, end == start, end > start],
        [EpisodeClass.INVALID.value, EpisodeClass.OPEN.value, EpisodeClass.INVALID.value,
         EpisodeClass.OUTPATIENT.value, EpisodeClass.INPATIENT.value],
        default=EpisodeClass.INVALID.value,
    )
    e["episode_class"] = cls
    # Délka pobytu = day_end − day_start bez +1; jen pro dokončené hospitalizace.
    e["los_days"] = np.where(cls == EpisodeClass.INPATIENT.value, end - start, np.nan)
    e["known_patient"] = e["patient_id"].isin(known_patients)
    return e


# ---------------------------------------------------------------------------
# Laboratoře
# ---------------------------------------------------------------------------


def normalize_labs(raw: pd.DataFrame, episodes_norm: pd.DataFrame, known_patients: set[str]) -> pd.DataFrame:
    lab = _strip_all(raw, LAB_COLUMNS)
    lab.insert(0, "lab_row", np.arange(len(lab)))
    lab["day_num"] = _to_int(lab["day"])
    lab["value_num"] = _to_float(lab["value"])
    lab["ref_low_num"] = _to_float(lab["ref_low"])
    lab["ref_high_num"] = _to_float(lab["ref_high"])
    owner = lab["episode_id"].map(dict(zip(episodes_norm["episode_id"], episodes_norm["patient_id"], strict=False)))
    lab["episode_link"] = np.select(
        [lab["episode_id"] == "", owner.isna(), owner != lab["patient_id"]],
        ["no_episode", "unknown_episode", "patient_mismatch"],
        default="linked",
    )
    # Vazba na epizodu jen při shodě obou klíčů; výsledek zůstává vždy u pacienta.
    lab["linked_episode_id"] = np.where(lab["episode_link"] == "linked", lab["episode_id"], "")
    lab["test_key"] = lab["test_code"] + "|" + lab["unit"]
    lab["test_label"] = lab["test_code"] + " · " + lab["panel"] + " · " + lab["unit"]
    lab["known_patient"] = lab["patient_id"].isin(known_patients)
    return lab
