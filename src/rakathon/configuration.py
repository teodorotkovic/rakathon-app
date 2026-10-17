"""Načtení a validace konfigurace (defaults.json, diagnostická mapa, proměnné prostředí)."""

from __future__ import annotations

import hashlib
import json
import os
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import pandas as pd

from rakathon.domain import AnalysisConfig, BaselineConfig

PROJECT_ROOT = Path(__file__).resolve().parents[2]
DEFAULTS_PATH = PROJECT_ROOT / "config" / "defaults.json"

VALID_EPISODE_RULES = ("exact_dx_match", "group_dx_match", "from_anchor_all_inpatient")
VALID_SCALES = ("log", "raw")
VALID_BASELINE_METHODS = ("peer_median", "ridge_loo")


class ConfigError(ValueError):
    pass


@dataclass(frozen=True)
class AppSettings:
    data_dir: Path
    runtime_dir: Path
    diagnosis_map_path: Path
    defaults: dict[str, Any]


def _resolve(path_str: str) -> Path:
    p = Path(path_str)
    return p if p.is_absolute() else PROJECT_ROOT / p


def load_defaults(path: Path = DEFAULTS_PATH) -> dict[str, Any]:
    with open(path, encoding="utf-8") as fh:
        return json.load(fh)


def load_settings(path: Path = DEFAULTS_PATH) -> AppSettings:
    defaults = load_defaults(path)
    paths = defaults.get("paths", {})
    data_dir = _resolve(os.environ.get("RAKATHON_DATA_DIR", paths.get("data_dir", "data")))
    runtime_dir = _resolve(os.environ.get("RAKATHON_RUNTIME_DIR", paths.get("runtime_dir", "runtime")))
    dxmap = _resolve(paths.get("diagnosis_map", "config/diagnosis_groups.csv"))
    return AppSettings(data_dir, runtime_dir, dxmap, defaults)


# ---------------------------------------------------------------------------
# Diagnostická mapa
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class DiagnosisMap:
    """Explicitní verzovaný číselník orientačních diagnostických skupin."""

    table: pd.DataFrame  # code, group_id, group_label, note, map_version
    version: str
    content_hash: str

    def group_of(self, code: str) -> str | None:
        hit = self._lookup().get(code)
        return hit[0] if hit else None

    def label_of_group(self, group_id: str | None) -> str:
        if not group_id:
            return "Nezařazeno (bez skupinového srovnání)"
        rows = self.table[self.table["group_id"] == group_id]
        return str(rows["group_label"].iloc[0]) if len(rows) else group_id

    def codes_in_group(self, group_id: str) -> list[str]:
        return sorted(self.table.loc[self.table["group_id"] == group_id, "code"].tolist())

    def note_of_group(self, group_id: str | None) -> str:
        if not group_id:
            return ""
        notes = self.table.loc[self.table["group_id"] == group_id, "note"]
        notes = [n for n in notes if n]
        return notes[0] if notes else ""

    def _lookup(self) -> dict[str, tuple[str, str]]:
        return {r.code: (r.group_id, r.group_label) for r in self.table.itertuples(index=False)}


def load_diagnosis_map(path: Path) -> DiagnosisMap:
    raw = path.read_bytes()
    table = pd.read_csv(path, dtype=str, keep_default_na=False, encoding="utf-8")
    required = {"code", "group_id", "group_label", "note", "map_version"}
    missing = required - set(table.columns)
    if missing:
        raise ConfigError(f"Diagnostické mapě chybí sloupce: {sorted(missing)}")
    if table["code"].duplicated().any():
        dup = table.loc[table["code"].duplicated(), "code"].tolist()
        raise ConfigError(f"Diagnostická mapa obsahuje duplicitní kódy: {dup}")
    versions = sorted(set(table["map_version"]))
    if len(versions) != 1:
        raise ConfigError(f"Diagnostická mapa musí mít jednu verzi, nalezeno: {versions}")
    return DiagnosisMap(table=table, version=versions[0], content_hash=hashlib.sha256(raw).hexdigest()[:12])


# ---------------------------------------------------------------------------
# Výchozí konfigurace
# ---------------------------------------------------------------------------


def default_baseline_config(settings: AppSettings, dxmap: DiagnosisMap) -> BaselineConfig:
    d = dict(settings.defaults.get("baseline", {}))
    d["diagnosis_map_version"] = dxmap.version
    d["diagnosis_map_hash"] = dxmap.content_hash
    cfg = BaselineConfig.from_dict(d)
    validate_baseline_config(cfg)
    return cfg


def default_analysis_config(settings: AppSettings) -> AnalysisConfig:
    cfg = AnalysisConfig.from_dict(settings.defaults.get("analysis", {}))
    validate_analysis_config(cfg)
    return cfg


def validate_baseline_config(cfg: BaselineConfig) -> None:
    if cfg.method not in VALID_BASELINE_METHODS:
        raise ConfigError(f"Neznámá metoda baseline: {cfg.method}")
    if cfg.ridge_alpha <= 0:
        raise ConfigError("ridge_alpha musí být kladné.")
    if cfg.episode_rule not in VALID_EPISODE_RULES:
        raise ConfigError(f"Neznámé pravidlo výběru epizod: {cfg.episode_rule}")
    if cfg.min_limited_reference < 1 or cfg.min_reference < cfg.min_limited_reference:
        raise ConfigError("Musí platit 1 ≤ min_limited_reference ≤ min_reference.")
    allowed = {"dx_icd10", "dx_group", "age_group", "sex"}
    for level in cfg.hierarchy:
        if not level or not set(level) <= allowed:
            raise ConfigError(f"Neplatná úroveň hierarchie: {level}")


def validate_analysis_config(cfg: AnalysisConfig) -> None:
    if not cfg.metrics:
        raise ConfigError("Analýza musí mít alespoň jeden ukazatel.")
    if cfg.scale not in VALID_SCALES:
        raise ConfigError(f"Neplatná škála: {cfg.scale}")
    if cfg.method != "robust_max_z":
        raise ConfigError(f"Neznámá lokální metoda: {cfg.method}")
    if cfg.threshold <= 0:
        raise ConfigError("Práh musí být kladný.")
    if cfg.cluster_method not in ("hierarchical", "kmeans"):
        raise ConfigError(f"Neznámý algoritmus shlukování: {cfg.cluster_method}")
    if cfg.cluster_linkage not in ("ward", "average", "complete"):
        raise ConfigError(f"Neznámý způsob spojování: {cfg.cluster_linkage}")
    if cfg.cluster_k is not None and cfg.cluster_k < 2:
        raise ConfigError("Počet shluků musí být alespoň 2.")
    if cfg.cluster_min_outliers < 2:
        raise ConfigError("Shlukování potřebuje alespoň 2 pacienty.")
