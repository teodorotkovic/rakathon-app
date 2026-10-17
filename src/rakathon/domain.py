"""Společné datové kontrakty mezi moduly.

Tento modul nesmí importovat Streamlit ani provádět I/O. Změna kontraktu se musí
promítnout do všech klientů v jednom kroku a zapsat do docs/architecture.md.
"""

from __future__ import annotations

import hashlib
import json
from dataclasses import asdict, dataclass, field
from enum import StrEnum
from typing import Any

import pandas as pd

from rakathon import __version__

# Verze, které mění význam výpočtu. Při změně agregace, baseline nebo detektoru zvyš
# příslušnou verzi, aby staré výsledky a anotace nepředstíraly totožnou analýzu.
FEATURE_SCHEMA_VERSION = "features-v1"
METHOD_VERSION = "method-v1"
APP_VERSION = __version__


class SourceMode(StrEnum):
    REAL = "real"


class Severity(StrEnum):
    BLOCKING = "blocking"
    WARNING = "warning"
    INFO = "info"


class FeatureRole(StrEnum):
    IDENTIFIER = "identifier"
    BASELINE_INPUT = "baseline_input"
    OUTCOME = "outcome"
    DESCRIPTOR = "descriptor"
    DATA_QUALITY = "data_quality"


class EpisodeClass(StrEnum):
    OUTPATIENT = "outpatient"
    INPATIENT = "inpatient_completed"
    OPEN = "inpatient_open"
    INVALID = "invalid_interval"


EPISODE_CLASS_LABELS = {
    EpisodeClass.OUTPATIENT: "Ambulantní kontakt",
    EpisodeClass.INPATIENT: "Dokončená hospitalizace",
    EpisodeClass.OPEN: "Pobyt bez zaznamenaného data propuštění",
    EpisodeClass.INVALID: "Neplatný interval (konec před začátkem)",
}


class OutcomeStatus(StrEnum):
    OK = "ok"
    SINGLE_STAY = "single_stay"
    NO_STAY = "no_relevant_stay"
    NO_ANCHOR = "no_anchor"
    EXCLUDED = "excluded"


class BaselineStatus(StrEnum):
    OK = "ok"
    LIMITED = "limited_reference"
    INSUFFICIENT = "insufficient_reference"
    EXCLUDED = "excluded"


BASELINE_STATUS_LABELS = {
    BaselineStatus.OK: "Reference dostatečná",
    BaselineStatus.LIMITED: "Omezená reference",
    BaselineStatus.INSUFFICIENT: "Nedostatek srovnatelných případů",
    BaselineStatus.EXCLUDED: "Vyřazen z výpočtu",
}


class ReviewStatus(StrEnum):
    NOT_REVIEWED = "not_reviewed"
    CLINICALLY_INTERESTING = "clinically_interesting"
    EXPLAINED_BY_CONTEXT = "explained_by_context"
    DATA_ISSUE = "suspected_data_issue"
    CANNOT_ASSESS = "cannot_assess"


REVIEW_LABELS = {
    ReviewStatus.NOT_REVIEWED: "Neposouzeno",
    ReviewStatus.CLINICALLY_INTERESTING: "Klinicky zajímavé",
    ReviewStatus.EXPLAINED_BY_CONTEXT: "Vysvětlitelné známým kontextem",
    ReviewStatus.DATA_ISSUE: "Podezření na datový problém",
    ReviewStatus.CANNOT_ASSESS: "Nelze posoudit",
}


def review_label(status: str) -> str:
    """Popisek stavu posouzení; neznámý stav se vrací raw (nikdy nevyhazuje)."""
    return {k.value: v for k, v in REVIEW_LABELS.items()}.get(
        status, status or REVIEW_LABELS[ReviewStatus.NOT_REVIEWED]
    )


def canonical_json(obj: Any) -> str:
    """Deterministická serializace pro hashování konfigurací."""
    return json.dumps(obj, sort_keys=True, ensure_ascii=False, separators=(",", ":"), default=str)


def stable_hash(obj: Any, length: int = 12) -> str:
    return hashlib.sha256(canonical_json(obj).encode("utf-8")).hexdigest()[:length]


# ---------------------------------------------------------------------------
# Validace a dataset
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class ValidationIssue:
    severity: Severity
    table: str
    column: str
    code: str
    message: str
    count: int = 0
    examples: tuple[str, ...] = ()


@dataclass
class ValidationReport:
    issues: list[ValidationIssue] = field(default_factory=list)

    @property
    def is_valid(self) -> bool:
        return not any(i.severity == Severity.BLOCKING for i in self.issues)

    def by_severity(self, severity: Severity) -> list[ValidationIssue]:
        return [i for i in self.issues if i.severity == severity]

    def to_frame(self) -> pd.DataFrame:
        rows = [
            {
                "severity": i.severity.value,
                "table": i.table,
                "column": i.column,
                "code": i.code,
                "count": i.count,
                "message": i.message,
                "examples": "; ".join(i.examples),
            }
            for i in self.issues
        ]
        return pd.DataFrame(
            rows, columns=["severity", "table", "column", "code", "count", "message", "examples"]
        )


@dataclass
class DatasetBundle:
    """Validovaný a normalizovaný dataset. Raw tabulky zůstávají beze změny."""

    raw: dict[str, pd.DataFrame]
    patients: pd.DataFrame  # normalizovaní pacienti (jeden řádek = pacient × nádor)
    episodes: pd.DataFrame  # normalizované epizody
    labs: pd.DataFrame  # normalizované laboratoře
    fingerprint: str
    source_mode: SourceMode
    source_label: str
    validation: ValidationReport
    extra: pd.DataFrame | None = None  # doplňkové vlastnosti (patient_id + sloupce)
    extra_meta: pd.DataFrame | None = None

    @property
    def short_fingerprint(self) -> str:
        return self.fingerprint[:12]


# ---------------------------------------------------------------------------
# Katalog vlastností a výsledků
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class FeatureSpec:
    id: str
    label: str
    description: str
    dtype: str  # "numeric" | "categorical" | "text" | "boolean"
    role: FeatureRole
    source: str
    unit: str = ""
    aggregation: str = ""
    missing_meaning: str = ""
    availability: str = ""
    order: tuple[str, ...] | None = None
    user_defined: bool = False


@dataclass(frozen=True)
class OutcomeSpec:
    id: str
    label: str
    short_label: str
    description: str
    unit: str
    statistic: str  # "median" | "max"
    time_policy: str
    evaluability: str


# ---------------------------------------------------------------------------
# Globální baseline
# ---------------------------------------------------------------------------

DEFAULT_HIERARCHY: tuple[tuple[str, ...], ...] = (
    ("dx_icd10", "age_group", "sex"),
    ("dx_icd10", "age_group"),
    ("dx_icd10",),
    ("dx_group", "age_group"),
    ("dx_group",),
)


@dataclass(frozen=True)
class BaselineConfig:
    method: str = "peer_median"
    episode_rule: str = "exact_dx_match"
    outcomes: tuple[str, ...] = ("median_los_dx", "max_los_dx")
    hierarchy: tuple[tuple[str, ...], ...] = DEFAULT_HIERARCHY
    min_reference: int = 8
    min_limited_reference: int = 4
    diagnosis_map_version: str = ""
    diagnosis_map_hash: str = ""
    excluded_patient_ids: tuple[str, ...] = ()
    exclusion_reasons: tuple[tuple[str, str], ...] = ()
    seed: int = 0
    ridge_alpha: float = 1.0  # jen pro method="ridge_loo"

    def to_dict(self) -> dict[str, Any]:
        d = asdict(self)
        d["hierarchy"] = [list(level) for level in self.hierarchy]
        d["outcomes"] = list(self.outcomes)
        d["excluded_patient_ids"] = list(self.excluded_patient_ids)
        d["exclusion_reasons"] = [list(p) for p in self.exclusion_reasons]
        return d

    @classmethod
    def from_dict(cls, d: dict[str, Any]) -> BaselineConfig:
        return cls(
            method=d.get("method", "peer_median"),
            episode_rule=d.get("episode_rule", "exact_dx_match"),
            outcomes=tuple(d.get("outcomes", ("median_los_dx", "max_los_dx"))),
            hierarchy=tuple(tuple(level) for level in d.get("hierarchy", DEFAULT_HIERARCHY)),
            min_reference=int(d.get("min_reference", 8)),
            min_limited_reference=int(d.get("min_limited_reference", 4)),
            diagnosis_map_version=d.get("diagnosis_map_version", ""),
            diagnosis_map_hash=d.get("diagnosis_map_hash", ""),
            excluded_patient_ids=tuple(sorted(d.get("excluded_patient_ids", ()))),
            exclusion_reasons=tuple(sorted(tuple(p) for p in d.get("exclusion_reasons", ()))),
            seed=int(d.get("seed", 0)),
            ridge_alpha=float(d.get("ridge_alpha", 1.0)),
        )

    @property
    def config_id(self) -> str:
        payload = {
            "config": self.to_dict(),
            "feature_schema_version": FEATURE_SCHEMA_VERSION,
            "method_version": METHOD_VERSION,
        }
        return "B-" + stable_hash(payload)


@dataclass
class BaselineResult:
    """Long tabulka: jeden řádek = pacient × výsledkový ukazatel."""

    table: pd.DataFrame
    config: BaselineConfig
    dataset_fingerprint: str
    source_mode: SourceMode
    generated_at: str
    meta: dict[str, Any] = field(default_factory=dict)

    @property
    def config_id(self) -> str:
        return self.config.config_id


# ---------------------------------------------------------------------------
# Lokální analýza odchylek
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class AnalysisConfig:
    metrics: tuple[str, ...] = ("median_los_dx",)
    scale: str = "log"  # "log" | "raw"
    method: str = "robust_max_z"
    threshold: float = 2.5
    margin: float = 1.0
    include_limited_reference: bool = True
    reference_ids: tuple[str, ...] | None = None  # None = všichni hodnotitelní pacienti
    reference_label: str = ""
    sensitivity_thresholds: tuple[float, ...] = (2.0, 2.5, 3.0, 3.5)
    min_calibration_n: int = 8
    min_support_stays: int = 2
    cluster_min_outliers: int = 4
    cluster_distance_threshold: float = 2.5

    def to_dict(self) -> dict[str, Any]:
        d = asdict(self)
        d["metrics"] = list(self.metrics)
        d["reference_ids"] = None if self.reference_ids is None else sorted(self.reference_ids)
        d["sensitivity_thresholds"] = list(self.sensitivity_thresholds)
        return d

    @classmethod
    def from_dict(cls, d: dict[str, Any]) -> AnalysisConfig:
        ref = d.get("reference_ids")
        return cls(
            metrics=tuple(d.get("metrics", ("median_los_dx",))),
            scale=d.get("scale", "log"),
            method=d.get("method", "robust_max_z"),
            threshold=float(d.get("threshold", 2.5)),
            margin=float(d.get("margin", 1.0)),
            include_limited_reference=bool(d.get("include_limited_reference", True)),
            reference_ids=None if ref is None else tuple(sorted(ref)),
            reference_label=d.get("reference_label", ""),
            sensitivity_thresholds=tuple(
                float(x) for x in d.get("sensitivity_thresholds", (2.0, 2.5, 3.0, 3.5))
            ),
            min_calibration_n=int(d.get("min_calibration_n", 8)),
            min_support_stays=int(d.get("min_support_stays", 2)),
            cluster_min_outliers=int(d.get("cluster_min_outliers", 4)),
            cluster_distance_threshold=float(d.get("cluster_distance_threshold", 2.5)),
        )

    def analysis_id(self, dataset_fingerprint: str, baseline_config_id: str) -> str:
        payload = {
            "dataset": dataset_fingerprint,
            "baseline": baseline_config_id,
            "analysis": self.to_dict(),
            "method_version": METHOD_VERSION,
        }
        return "A-" + stable_hash(payload)


@dataclass
class AnalysisResult:
    """Výsledek lokální analýzy.

    scores: jeden řádek na hodnoceného pacienta (včetně neskórovaných se stavem a důvodem).
    dims: long tabulka pacient × metrika se standardizací.
    calibration: parametry standardizace po metrikách (lokální reference).
    clusters: přiřazení outlierů do skupin.
    groups: popisy skupin (long tabulka pro export) a seznam textových shrnutí.
    """

    analysis_id: str
    config: AnalysisConfig
    baseline_config_id: str
    dataset_fingerprint: str
    source_mode: SourceMode
    generated_at: str
    scores: pd.DataFrame
    dims: pd.DataFrame
    calibration: pd.DataFrame
    clusters: pd.DataFrame
    cluster_info: dict[str, Any]
    group_summary: pd.DataFrame
    group_cards: list[dict[str, Any]]
    reference_ids: tuple[str, ...]
    meta: dict[str, Any] = field(default_factory=dict)


# ---------------------------------------------------------------------------
# Posouzení lékařem
# ---------------------------------------------------------------------------

REVIEW_COLUMNS = [
    "record_id",
    "dataset_fingerprint",
    "source_mode",
    "patient_id",
    "baseline_config_id",
    "analysis_id",
    "analysis_label",
    "status",
    "comment",
    "reviewer",
    "created_at",
    "supersedes",
]


@dataclass(frozen=True)
class ReviewRecord:
    record_id: str
    dataset_fingerprint: str
    source_mode: str
    patient_id: str
    baseline_config_id: str
    analysis_id: str
    analysis_label: str
    status: str
    comment: str
    reviewer: str
    created_at: str
    supersedes: str = ""

    def to_row(self) -> dict[str, str]:
        return {k: str(v) for k, v in asdict(self).items()}
