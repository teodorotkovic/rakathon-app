"""Společný stav aplikace a cache výpočtů.

Tři odlišné množiny pacientů (viz docs/architecture.md):
1. globální baseline – mění se jen formulářem „Přepočítat očekávání“ (K_BASELINE),
2. lokální reference analýzy – AnalysisConfig.reference_ids (K_ANALYSIS),
3. vyšetřovaný/zobrazený výběr – K_INVESTIGATED (nic nepřepočítává).

Cache výpočtů je klíčovaná otiskem datasetu (+ doplňkových vlastností) a kanonickým
JSON konfigurace. Posouzení se necachují – čtou se z úložiště při každém běhu.
"""

from __future__ import annotations

import json
from dataclasses import replace

import pandas as pd
import streamlit as st

from rakathon.configuration import (
    AppSettings,
    DiagnosisMap,
    default_analysis_config,
    default_baseline_config,
    load_diagnosis_map,
    load_settings,
)
from rakathon.data.dataset import prepare_dataset
from rakathon.data.io import DatasetFilesMissing, dataset_dir_available, read_dataset_dir
from rakathon.domain import (
    AnalysisConfig,
    AnalysisResult,
    BaselineConfig,
    DatasetBundle,
    SourceMode,
    ValidationReport,
    canonical_json,
    stable_hash,
)
from rakathon.features.extra import apply_meta
from rakathon.pipeline import GlobalResults, compute_analysis, compute_global
from rakathon.storage.csv_store import CsvStore, current_reviews

K_DATASET = "dataset"
K_BASELINE = "baseline_config"
K_ANALYSIS = "analysis_config"
K_SELECTED = "selected_patient_id"
K_FROM_ANALYSIS = "detail_from_analysis"
K_INVESTIGATED = "investigated_ids"
K_FOCUS = "analysis_focus_id"
K_PENDING_EXCL = "pending_exclusions"
K_IMPORT_REPORT = "last_failed_import_report"
K_NONCE = "widget_nonce"
K_FLASH = "flash_message"
K_REVIEWER = "reviewer_label"

PATIENTS_PAGE = "views/patients.py"
DEVIATIONS_PAGE = "views/deviations.py"


@st.cache_resource
def settings() -> AppSettings:
    return load_settings()


@st.cache_resource
def _dxmap_cached(path: str, mtime: float) -> DiagnosisMap:
    from pathlib import Path

    return load_diagnosis_map(Path(path))


def dxmap() -> DiagnosisMap:
    p = settings().diagnosis_map_path
    return _dxmap_cached(str(p), p.stat().st_mtime)


# ---------------------------------------------------------------------------
# Dataset
# ---------------------------------------------------------------------------


@st.cache_data(show_spinner="Ověřuji a normalizuji data…", max_entries=4)
def _prepare_cached(
    fingerprint_key: str, _files: dict[str, bytes], mode: str, label: str, _dx: DiagnosisMap, dx_hash: str
):
    return prepare_dataset(_files, SourceMode(mode), label, _dx)


def _fingerprint(files: dict[str, bytes]) -> str:
    from rakathon.data.io import fingerprint_files

    return fingerprint_files(files)


def activate_files(files: dict[str, bytes], mode: SourceMode, label: str) -> tuple[bool, ValidationReport]:
    """Jeden validovaný krok. Při neúspěchu zůstává aktivní původní dataset."""
    dx = dxmap()
    bundle, report = _prepare_cached(_fingerprint(files), files, mode.value, label, dx, dx.content_hash)
    if bundle is None:
        st.session_state[K_IMPORT_REPORT] = report
        return False, report
    st.session_state.pop(K_IMPORT_REPORT, None)
    _attach_saved_extra(bundle)
    previous = st.session_state.get(K_DATASET)
    st.session_state[K_DATASET] = bundle
    if (
        previous is None
        or previous.fingerprint != bundle.fingerprint
        or previous.source_mode != bundle.source_mode
    ):
        reset_dataset_dependent_state()
    return True, report


def _attach_saved_extra(bundle: DatasetBundle) -> None:
    extra, meta = store_for(bundle).load_extra()
    if extra is not None and meta is not None:
        typed, _ = apply_meta(extra, meta)
        bundle.extra, bundle.extra_meta = typed, meta
    else:
        bundle.extra, bundle.extra_meta = None, None


def load_local_dir() -> tuple[bool, ValidationReport | str]:
    s = settings()
    try:
        files = read_dataset_dir(s.data_dir)
    except DatasetFilesMissing as exc:
        return False, str(exc)
    return activate_files(files, SourceMode.REAL, f"Lokální adresář {s.data_dir.name}/")


def reset_dataset_dependent_state() -> None:
    """Při změně datasetu odstraň výběry, reference a čekající vyřazení; konfigurace na výchozí."""
    st.session_state[K_SELECTED] = None
    st.session_state[K_FROM_ANALYSIS] = False
    st.session_state[K_INVESTIGATED] = []
    st.session_state[K_FOCUS] = None
    st.session_state[K_PENDING_EXCL] = {}
    st.session_state[K_BASELINE] = default_baseline_config(settings(), dxmap())
    st.session_state[K_ANALYSIS] = default_analysis_config(settings())
    bump_nonce()


def init() -> None:
    ss = st.session_state
    ss.setdefault(K_NONCE, 0)
    ss.setdefault(K_REVIEWER, "")
    if K_DATASET not in ss and dataset_dir_available(settings().data_dir):
        load_local_dir()
    ss.setdefault(K_BASELINE, default_baseline_config(settings(), dxmap()))
    ss.setdefault(K_ANALYSIS, default_analysis_config(settings()))
    ss.setdefault(K_SELECTED, None)
    ss.setdefault(K_FROM_ANALYSIS, False)
    ss.setdefault(K_INVESTIGATED, [])
    ss.setdefault(K_FOCUS, None)
    ss.setdefault(K_PENDING_EXCL, {})


def has_dataset() -> bool:
    return st.session_state.get(K_DATASET) is not None


def dataset() -> DatasetBundle:
    return st.session_state[K_DATASET]


def bump_nonce() -> None:
    st.session_state[K_NONCE] = st.session_state.get(K_NONCE, 0) + 1


def nonce() -> int:
    return st.session_state.get(K_NONCE, 0)


# ---------------------------------------------------------------------------
# Výpočty
# ---------------------------------------------------------------------------


def _dataset_key(bundle: DatasetBundle) -> str:
    extra_key = ""
    if bundle.extra is not None and bundle.extra_meta is not None:
        extra_key = stable_hash(
            [bundle.extra.astype(str).to_csv(index=False), bundle.extra_meta.to_dict("records")]
        )
    return f"{bundle.source_mode.value}:{bundle.fingerprint}:{extra_key}"


@st.cache_data(show_spinner="Počítám očekávání…", max_entries=8)
def _global_cached(
    dataset_key: str, config_json: str, _bundle: DatasetBundle, _dx: DiagnosisMap
) -> GlobalResults:
    return compute_global(_bundle, BaselineConfig.from_dict(json.loads(config_json)), _dx)


def baseline_config() -> BaselineConfig:
    return st.session_state[K_BASELINE]


def global_results() -> GlobalResults:
    bundle = dataset()
    cfg = baseline_config()
    return _global_cached(_dataset_key(bundle), canonical_json(cfg.to_dict()), bundle, dxmap())


@st.cache_data(show_spinner="Počítám analýzu odchylek…", max_entries=24)
def _analysis_cached(
    dataset_key: str, baseline_id: str, analysis_json: str, _g: GlobalResults
) -> AnalysisResult:
    return compute_analysis(_g, AnalysisConfig.from_dict(json.loads(analysis_json)))


def analysis_config() -> AnalysisConfig:
    return st.session_state[K_ANALYSIS]


def set_analysis_config(cfg: AnalysisConfig) -> None:
    st.session_state[K_ANALYSIS] = cfg


def analysis_for(cfg: AnalysisConfig) -> AnalysisResult:
    g = global_results()
    valid = tuple(m for m in cfg.metrics if m in g.baseline.config.outcomes) or (
        g.baseline.config.outcomes[0],
    )
    if valid != cfg.metrics:
        cfg = replace(cfg, metrics=valid)
    return _analysis_cached(_dataset_key(dataset()), g.baseline_config_id, canonical_json(cfg.to_dict()), g)


def default_analysis() -> AnalysisResult:
    """Výchozí pohled (stránka Pacienti) – nezávislý na experimentech v Analýze odchylek."""
    return analysis_for(default_analysis_config(settings()))


def local_analysis() -> AnalysisResult:
    return analysis_for(analysis_config())


# ---------------------------------------------------------------------------
# Úložiště a posouzení
# ---------------------------------------------------------------------------


def store_for(bundle: DatasetBundle) -> CsvStore:
    return CsvStore(settings().runtime_dir, bundle.source_mode.value, bundle.fingerprint)


def store() -> CsvStore:
    return store_for(dataset())


def reviews_all() -> pd.DataFrame:
    return store().load_reviews()


def reviews_current() -> pd.DataFrame:
    g = global_results()
    return current_reviews(reviews_all(), g.dataset_fingerprint, g.baseline_config_id)


def flash(kind: str, message: str) -> None:
    st.session_state[K_FLASH] = (kind, message)


def show_flash() -> None:
    msg = st.session_state.pop(K_FLASH, None)
    if msg:
        kind, text = msg
        getattr(st, kind if kind in ("success", "info", "warning", "error") else "info")(text)


def open_patient(pid: str, from_analysis: bool = False) -> None:
    st.session_state[K_SELECTED] = pid
    st.session_state[K_FROM_ANALYSIS] = from_analysis
