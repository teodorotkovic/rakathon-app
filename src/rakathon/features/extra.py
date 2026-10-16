"""Import doplňkových pacientských vlastností (extra_features.csv).

Jeden řádek na patient_id, libovolné nové sloupce. Nikdy nepřepisuje základní
sloupce, nic nevykonává (žádné eval/SQL), hodnoty se čtou jako text. Nová vlastnost
je popisná (descriptor) – není automaticky prognostickým faktorem ani výsledkem.
"""

from __future__ import annotations

import pandas as pd

from rakathon.data.io import parse_csv_text
from rakathon.data.validation import NUM_RE
from rakathon.domain import Severity, ValidationIssue

NAME_RE = r"[A-Za-z][A-Za-z0-9_]{0,40}"
ALLOWED_DTYPES = ("numeric", "categorical")
ALLOWED_ROLES = ("descriptor",)
META_COLUMNS = ["column", "label", "dtype", "unit", "role", "description"]


def parse_extra(content: bytes) -> pd.DataFrame:
    return parse_csv_text(content)


def validate_extra(
    df: pd.DataFrame, dataset_patient_ids: set[str], reserved: set[str]
) -> tuple[pd.DataFrame | None, list[ValidationIssue]]:
    """Vrací očištěnou tabulku (text) nebo None při blokující chybě."""
    issues: list[ValidationIssue] = []
    t = "extra_features"
    if "patient_id" not in df.columns:
        issues.append(
            ValidationIssue(Severity.BLOCKING, t, "patient_id", "missing_key", "Chybí sloupec patient_id.", 1)
        )
        return None, issues
    df = df.copy()
    df["patient_id"] = df["patient_id"].astype(str).str.strip()
    empty = df["patient_id"] == ""
    if empty.any():
        issues.append(
            ValidationIssue(
                Severity.BLOCKING, t, "patient_id", "missing_key", "Prázdné patient_id.", int(empty.sum())
            )
        )
    dup = df["patient_id"].duplicated(keep=False) & ~empty
    if dup.any():
        issues.append(
            ValidationIssue(
                Severity.BLOCKING,
                t,
                "patient_id",
                "duplicate_key",
                "patient_id není unikátní – vlastnost by zdvojila pacienty.",
                int(dup.sum()),
                tuple(df.loc[dup, "patient_id"].unique()[:5]),
            )
        )
    if any(i.severity == Severity.BLOCKING for i in issues):
        return None, issues

    unknown = ~df["patient_id"].isin(dataset_patient_ids)
    if unknown.any():
        issues.append(
            ValidationIssue(
                Severity.WARNING,
                t,
                "patient_id",
                "unknown_patient",
                "Řádky s pacientem mimo aktivní dataset byly vynechány.",
                int(unknown.sum()),
                tuple(df.loc[unknown, "patient_id"].unique()[:5]),
            )
        )
        df = df[~unknown]
    missing = len(dataset_patient_ids - set(df["patient_id"]))
    if missing:
        issues.append(
            ValidationIssue(
                Severity.INFO,
                t,
                "patient_id",
                "missing_patients",
                "Pacienti bez řádku v souboru budou mít chybějící hodnotu.",
                missing,
            )
        )

    keep = ["patient_id"]
    for col in df.columns:
        if col == "patient_id":
            continue
        if not pd.Series([col]).str.fullmatch(NAME_RE).iloc[0]:
            issues.append(
                ValidationIssue(
                    Severity.WARNING,
                    t,
                    col,
                    "invalid_name",
                    "Neplatný název sloupce (povoleno A–Z, a–z, 0–9, _; začíná písmenem) – vynechán.",
                    1,
                )
            )
            continue
        if col in reserved:
            issues.append(
                ValidationIssue(
                    Severity.WARNING,
                    t,
                    col,
                    "reserved_name",
                    "Název koliduje se základním nebo odvozeným sloupcem – vynechán, nic se nepřepisuje.",
                    1,
                )
            )
            continue
        keep.append(col)
    if len(keep) == 1:
        issues.append(
            ValidationIssue(
                Severity.BLOCKING, t, "", "no_columns", "Soubor neobsahuje žádný použitelný sloupec.", 1
            )
        )
        return None, issues
    return df[keep].reset_index(drop=True), issues


def infer_meta(df: pd.DataFrame) -> pd.DataFrame:
    rows = []
    for col in df.columns:
        if col == "patient_id":
            continue
        s = df[col].astype(str).str.strip()
        nonempty = s[s != ""]
        numeric = len(nonempty) > 0 and bool(nonempty.str.fullmatch(NUM_RE).all())
        rows.append(
            {
                "column": col,
                "label": col,
                "dtype": "numeric" if numeric else "categorical",
                "unit": "",
                "role": "descriptor",
                "description": "",
            }
        )
    return pd.DataFrame(rows, columns=META_COLUMNS)


def validate_meta(meta: pd.DataFrame, extra: pd.DataFrame) -> list[ValidationIssue]:
    issues: list[ValidationIssue] = []
    t = "extra_features_meta"
    for row in meta.itertuples(index=False):
        if row.column not in extra.columns:
            issues.append(
                ValidationIssue(
                    Severity.BLOCKING,
                    t,
                    row.column,
                    "unknown_column",
                    "Metadata k neexistujícímu sloupci.",
                    1,
                )
            )
        if row.dtype not in ALLOWED_DTYPES:
            issues.append(
                ValidationIssue(
                    Severity.BLOCKING, t, row.column, "dtype", f"Typ musí být jeden z {ALLOWED_DTYPES}.", 1
                )
            )
        if row.role not in ALLOWED_ROLES:
            issues.append(
                ValidationIssue(
                    Severity.BLOCKING,
                    t,
                    row.column,
                    "role",
                    "Doplňková vlastnost může mít v této verzi jen roli 'descriptor'. Vstup do baseline vyžaduje "
                    "doloženou časovou dostupnost a novou konfiguraci; nový výsledek vyžaduje definici a agregaci.",
                    1,
                )
            )
        if not str(row.label).strip():
            issues.append(ValidationIssue(Severity.BLOCKING, t, row.column, "label", "Chybí popisek.", 1))
    return issues


def apply_meta(extra: pd.DataFrame, meta: pd.DataFrame) -> tuple[pd.DataFrame, list[ValidationIssue]]:
    """Převede sloupce na deklarované typy. Nepřevoditelné hodnoty → chybějící + varování."""
    issues: list[ValidationIssue] = []
    out = extra[["patient_id"]].copy()
    for row in meta.itertuples(index=False):
        s = extra[row.column].astype(str).str.strip()
        if row.dtype == "numeric":
            ok = s.str.fullmatch(NUM_RE).fillna(False).astype(bool)
            bad = (s != "") & ~ok
            if bad.any():
                issues.append(
                    ValidationIssue(
                        Severity.WARNING,
                        "extra_features",
                        row.column,
                        "not_numeric",
                        "Hodnoty nelze převést na číslo – vedeny jako chybějící.",
                        int(bad.sum()),
                    )
                )
            out[row.column] = pd.to_numeric(s.where(ok), errors="coerce").astype(float)
        else:
            out[row.column] = s.where(s != "", None).astype(object)
    return out, issues
