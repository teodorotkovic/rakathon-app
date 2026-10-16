"""Validace vstupních tabulek podle datapackage.json.

Blokující chyby (chybějící sloupce/klíče, nejednoznačné duplicity, nečitelný povinný
údaj) zabrání aktivaci datasetu. Neblokující omezení se zobrazí a promítnou do
stavů výpočtu, ale dataset zůstane použitelný.
"""

from __future__ import annotations

import pandas as pd

from rakathon.domain import Severity, ValidationIssue, ValidationReport

PATIENT_COLUMNS = [
    "patient_id", "tumor_id", "sex", "age_group", "dx_icd10", "topography_icdo3", "morphology_icdo3",
    "laterality", "grade", "stage", "extent", "t", "n", "m", "pt", "pn", "psu", "pm", "deceased",
]
EPISODE_COLUMNS = ["patient_id", "episode_id", "day_start", "day_end", "dx_main"]
LAB_COLUMNS = ["patient_id", "episode_id", "day", "test_code", "panel", "value", "unit", "ref_low", "ref_high", "flag"]
REQUIRED_COLUMNS = {"patients": PATIENT_COLUMNS, "episodes": EPISODE_COLUMNS, "labs": LAB_COLUMNS}

AGE_GROUPS = ["0-5", "6-8", "9-11", "12-14", "15-17", "18-20"]
SEX_VALUES = ["M", "F"]
PANELS = ["biochemistry", "blood_count", "coagulation", "differential"]
FLAGS = ["L", "N", "H", ""]

PID_RE = r"P[0-9]{4,}"
EPISODE_RE = r"P[0-9]{4,}-E[0-9]{3,}"
DX_RE = r"[A-Z][0-9]{2}"
MORPH_RE = r"[0-9]{4}/[0-9]"
INT_RE = r"-?[0-9]+"
NUM_RE = r"-?[0-9]+(\.[0-9]+)?([eE][-+]?[0-9]+)?"

MAX_EXAMPLES = 5


def _examples(values: pd.Series) -> tuple[str, ...]:
    return tuple(str(v) for v in pd.unique(values)[:MAX_EXAMPLES])


class _Collector:
    def __init__(self) -> None:
        self.issues: list[ValidationIssue] = []

    def add(self, severity: Severity, table: str, column: str, code: str, message: str,
            mask: pd.Series | None = None, ids: pd.Series | None = None, count: int | None = None) -> None:
        if mask is not None:
            n = int(mask.sum())
            if n == 0:
                return
            examples = _examples(ids[mask]) if ids is not None else ()
        else:
            n = int(count or 0)
            examples = ()
        self.issues.append(ValidationIssue(severity, table, column, code, message, n, examples))


def _not_matching(series: pd.Series, pattern: str) -> pd.Series:
    return ~series.str.fullmatch(pattern).fillna(False).astype(bool)


def validate_tables(tables: dict[str, pd.DataFrame]) -> ValidationReport:
    c = _Collector()

    # --- povinné sloupce ---
    ok_tables: dict[str, pd.DataFrame] = {}
    for name, required in REQUIRED_COLUMNS.items():
        df = tables.get(name)
        if df is None:
            c.add(Severity.BLOCKING, name, "", "missing_table", f"Chybí tabulka {name}.csv.", count=1)
            continue
        missing = [col for col in required if col not in df.columns]
        if missing:
            c.add(Severity.BLOCKING, name, ", ".join(missing), "missing_columns",
                  f"Chybí povinné sloupce: {', '.join(missing)}.", count=len(missing))
            continue
        extra = [col for col in df.columns if col not in required]
        if extra:
            c.add(Severity.INFO, name, ", ".join(extra), "extra_columns",
                  "Nadbytečné sloupce budou zachovány v raw datech, ale nepoužijí se.", count=len(extra))
        if len(df) == 0:
            if name == "patients":
                c.add(Severity.BLOCKING, name, "", "empty_table", "Tabulka patients je prázdná.", count=1)
                continue
            c.add(Severity.WARNING if name == "episodes" else Severity.INFO, name, "", "empty_table",
                  f"Tabulka {name} neobsahuje žádné řádky.", count=1)
        ok_tables[name] = df

    if "patients" in ok_tables:
        _validate_patients(ok_tables["patients"], c)
    if "episodes" in ok_tables:
        _validate_episodes(ok_tables["episodes"], ok_tables.get("patients"), c)
    if "labs" in ok_tables:
        _validate_labs(ok_tables["labs"], ok_tables.get("patients"), ok_tables.get("episodes"), c)
    return ValidationReport(c.issues)


def _validate_patients(p: pd.DataFrame, c: _Collector) -> None:
    pid = p["patient_id"].str.strip()
    t = "patients"
    c.add(Severity.BLOCKING, t, "patient_id", "missing_key", "Chybí patient_id.", pid == "", pid)
    c.add(Severity.WARNING, t, "patient_id", "pattern",
          "patient_id neodpovídá tvaru P0001.", (pid != "") & _not_matching(pid, PID_RE), pid)
    tumor = p["tumor_id"].str.strip()
    bad_tumor = _not_matching(tumor, r"[1-9][0-9]*")
    c.add(Severity.BLOCKING, t, "tumor_id", "invalid_key", "tumor_id není celé číslo ≥ 1.", bad_tumor, pid)
    dup = p.assign(_pid=pid, _t=tumor).duplicated(["_pid", "_t"], keep=False)
    c.add(Severity.BLOCKING, t, "patient_id, tumor_id", "duplicate_key",
          "Duplicitní kombinace (patient_id, tumor_id) – nejednoznačný záznam.", dup, pid)
    n_tumors = pid.map(pid.value_counts())
    c.add(Severity.WARNING, t, "tumor_id", "multi_tumor",
          "Pacient má více nádorových řádků. Přiřazení epizod k nádorům není určeno, "
          "proto je pacient zobrazen, ale vyřazen z baseline.", (n_tumors > 1) & ~dup, pid)
    c.add(Severity.WARNING, t, "sex", "enum", "Neznámá hodnota pohlaví (očekáváno M/F).",
          ~p["sex"].isin(SEX_VALUES), pid)
    c.add(Severity.WARNING, t, "age_group", "enum", "Neznámá věková skupina.",
          ~p["age_group"].isin(AGE_GROUPS), pid)
    dx = p["dx_icd10"].str.strip()
    c.add(Severity.WARNING, t, "dx_icd10", "missing", "Chybí diagnóza nádoru – nelze vytvořit očekávání.",
          dx == "", pid)
    c.add(Severity.WARNING, t, "dx_icd10", "pattern", "Diagnóza neodpovídá tvaru MKN-10 (např. C91).",
          (dx != "") & _not_matching(dx, DX_RE), pid)
    morph = p["morphology_icdo3"].str.strip()
    c.add(Severity.WARNING, t, "morphology_icdo3", "pattern", "Morfologie neodpovídá tvaru NNNN/B.",
          (morph != "") & _not_matching(morph, MORPH_RE), pid)
    c.add(Severity.INFO, t, "morphology_icdo3", "placeholder",
          "Kód 3333/3 je zástupná/neplatná hodnota – uchován raw, interpretován jako neznámý.",
          morph == "3333/3", pid)
    c.add(Severity.INFO, t, "stage", "unconfirmed_code",
          "Stadium 7 má nepotvrzený význam; nepoužívá se jako stadium ani pro výpočet.",
          p["stage"].str.strip() == "7", pid)
    c.add(Severity.WARNING, t, "deceased", "enum", "deceased má mít hodnotu 0/1.",
          ~p["deceased"].isin(["0", "1"]), pid)


def _validate_episodes(e: pd.DataFrame, p: pd.DataFrame | None, c: _Collector) -> None:
    t = "episodes"
    pid = e["patient_id"].str.strip()
    eid = e["episode_id"].str.strip()
    c.add(Severity.BLOCKING, t, "patient_id", "missing_key", "Chybí patient_id.", pid == "", eid)
    c.add(Severity.BLOCKING, t, "episode_id", "missing_key", "Chybí episode_id.", eid == "", pid)
    c.add(Severity.BLOCKING, t, "episode_id", "duplicate_key", "Duplicitní episode_id.",
          (eid != "") & eid.duplicated(keep=False), eid)
    prefix = eid.str.split("-E").str[0]
    c.add(Severity.BLOCKING, t, "episode_id", "patient_mismatch",
          "episode_id nepatří uvedenému patient_id – vazba je nejednoznačná.",
          (eid != "") & (pid != "") & (prefix != pid), eid)
    c.add(Severity.WARNING, t, "episode_id", "pattern", "episode_id neodpovídá tvaru P0001-E001.",
          (eid != "") & _not_matching(eid, EPISODE_RE), eid)
    if p is not None:
        known = set(p["patient_id"].str.strip())
        c.add(Severity.WARNING, t, "patient_id", "unknown_patient",
              "Epizoda patří pacientovi, který není v patients.csv – nebude použita.",
              (pid != "") & ~pid.isin(known), eid)
    ds = e["day_start"].str.strip()
    de = e["day_end"].str.strip()
    c.add(Severity.BLOCKING, t, "day_start", "not_integer", "day_start chybí nebo není celé číslo.",
          _not_matching(ds, INT_RE), eid)
    bad_end = (de != "") & _not_matching(de, INT_RE)
    c.add(Severity.WARNING, t, "day_end", "not_integer",
          "day_end není celé číslo – epizoda bude vedena jako neplatný interval.", bad_end, eid)
    ds_num = pd.to_numeric(ds.where(~_not_matching(ds, INT_RE)), errors="coerce")
    de_num = pd.to_numeric(de.where(~_not_matching(de, INT_RE)), errors="coerce")
    c.add(Severity.WARNING, t, "day_start", "negative", "day_start je záporný (schéma uvádí minimum 0).",
          ds_num < 0, eid)
    c.add(Severity.WARNING, t, "day_end", "invalid_interval",
          "day_end < day_start – neplatný interval; ponechán v auditu, nepoužije se jako délka.",
          de_num < ds_num, eid)
    c.add(Severity.INFO, t, "day_end", "open_stay",
          "Hospitalizace bez známého propuštění (day_end chybí) – délka se nedoplňuje.", de == "", eid)
    dx = e["dx_main"].str.strip()
    c.add(Severity.INFO, t, "dx_main", "missing", "Hlavní diagnóza epizody není kódována.", dx == "", eid)
    c.add(Severity.WARNING, t, "dx_main", "pattern", "dx_main neodpovídá tvaru MKN-10.",
          (dx != "") & _not_matching(dx, DX_RE), eid)


def _validate_labs(lab: pd.DataFrame, p: pd.DataFrame | None, e: pd.DataFrame | None, c: _Collector) -> None:
    t = "labs"
    pid = lab["patient_id"].str.strip()
    eid = lab["episode_id"].str.strip()
    c.add(Severity.BLOCKING, t, "patient_id", "missing_key", "Laboratoř bez patient_id.", pid == "", pid)
    if p is not None:
        known = set(p["patient_id"].str.strip())
        c.add(Severity.WARNING, t, "patient_id", "unknown_patient",
              "Výsledek patří pacientovi mimo patients.csv – nebude použit.",
              (pid != "") & ~pid.isin(known), pid)
    c.add(Severity.INFO, t, "episode_id", "no_episode",
          "Výsledek mimo epizodu (prázdné episode_id) – vazba na pacienta zůstává.", eid == "", pid)
    if e is not None:
        ep_owner = dict(zip(e["episode_id"].str.strip(), e["patient_id"].str.strip(), strict=False))
        owner = eid.map(ep_owner)
        c.add(Severity.WARNING, t, "episode_id", "unknown_episode",
              "episode_id neexistuje v episodes.csv – vazba na epizodu se nepoužije, výsledek zůstává u pacienta.",
              (eid != "") & owner.isna(), eid)
        c.add(Severity.WARNING, t, "episode_id", "patient_mismatch",
              "episode_id patří jinému pacientovi – vazba na epizodu se nepoužije.",
              (eid != "") & owner.notna() & (owner != pid), eid)
    day = lab["day"].str.strip()
    c.add(Severity.WARNING, t, "day", "not_integer", "day chybí nebo není celé číslo – výsledek bez časové polohy.",
          _not_matching(day, INT_RE), pid)
    day_num = pd.to_numeric(day.where(~_not_matching(day, INT_RE)), errors="coerce")
    c.add(Severity.INFO, t, "day", "negative", "Záporný den odběru (před první epizodou) – není chyba.",
          day_num < 0, pid)
    code = lab["test_code"].str.strip()
    c.add(Severity.WARNING, t, "test_code", "pattern", "test_code není pětimístný text.",
          _not_matching(code, r"[0-9]{5}"), pid)
    c.add(Severity.WARNING, t, "value", "not_numeric", "Hodnota není číslo – výsledek se nepoužije v souhrnech.",
          _not_matching(lab["value"].str.strip(), NUM_RE), pid)
    c.add(Severity.WARNING, t, "panel", "enum", "Neznámý panel.", ~lab["panel"].isin(PANELS), pid)
    c.add(Severity.WARNING, t, "flag", "enum", "Neznámý příznak (očekáváno L/N/H/prázdné).",
          ~lab["flag"].isin(FLAGS), pid)
    no_range = (lab["ref_low"].str.strip() == "") | (lab["ref_high"].str.strip() == "")
    c.add(Severity.INFO, t, "ref_low, ref_high", "missing_range", "Chybí referenční meze.", no_range, pid)
    dup = lab.duplicated(keep=False)
    c.add(Severity.INFO, t, "", "duplicate_rows",
          "Shodné řádky výsledků – ponechány (mohou být skutečně opakovaným měřením).", dup, pid)
