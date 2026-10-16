"""Orchestrace importu: parsování → validace → normalizace → DatasetBundle.

Import je jeden validovaný krok. Při blokující chybě se vrací None a volající
ponechá aktivní původní platný dataset.
"""

from __future__ import annotations

import pandas as pd

from rakathon.configuration import DiagnosisMap
from rakathon.data.io import TABLE_FILES, fingerprint_files, parse_csv_text
from rakathon.data.normalization import normalize_episodes, normalize_labs, normalize_patients
from rakathon.data.validation import validate_tables
from rakathon.domain import DatasetBundle, Severity, SourceMode, ValidationIssue, ValidationReport


def parse_tables(files: dict[str, bytes]) -> tuple[dict[str, pd.DataFrame], list[ValidationIssue]]:
    tables: dict[str, pd.DataFrame] = {}
    issues: list[ValidationIssue] = []
    for name in TABLE_FILES:
        content = files.get(name)
        if content is None:
            continue
        try:
            tables[name] = parse_csv_text(content)
        except UnicodeDecodeError as exc:
            issues.append(ValidationIssue(Severity.BLOCKING, name, "", "encoding",
                                          f"Soubor není v kódování UTF-8: {exc}", 1))
        except (pd.errors.ParserError, pd.errors.EmptyDataError) as exc:
            issues.append(ValidationIssue(Severity.BLOCKING, name, "", "parse_error",
                                          f"CSV nelze načíst: {exc}", 1))
    return tables, issues


def prepare_dataset(
    files: dict[str, bytes],
    source_mode: SourceMode,
    source_label: str,
    dxmap: DiagnosisMap,
) -> tuple[DatasetBundle | None, ValidationReport]:
    tables, parse_issues = parse_tables(files)
    report = validate_tables(tables)
    report = ValidationReport(parse_issues + report.issues)
    if not report.is_valid:
        return None, report

    patients = normalize_patients(tables["patients"], dxmap)
    known = set(patients["patient_id"])
    episodes = normalize_episodes(tables["episodes"], known)
    labs = normalize_labs(tables["labs"], episodes, known)
    bundle = DatasetBundle(
        raw=tables,
        patients=patients,
        episodes=episodes,
        labs=labs,
        fingerprint=fingerprint_files(files),
        source_mode=source_mode,
        source_label=source_label,
        validation=report,
    )
    return bundle, report
