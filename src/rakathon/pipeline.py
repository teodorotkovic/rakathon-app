"""Čisté služby výpočtu: globální baseline a lokální analýza.

UI tyto funkce volá přes cache klíčovanou otiskem datasetu a hashem konfigurace.
Modul neimportuje Streamlit a nečte globální stav UI.
"""

from __future__ import annotations

import platform
from dataclasses import dataclass, field
from datetime import UTC, datetime
from importlib import metadata

import pandas as pd

from rakathon.analysis.clustering import cluster_outliers
from rakathon.analysis.detectors import run_robust_detector
from rakathon.analysis.explanations import describe_groups
from rakathon.analysis.residuals import attach_residuals
from rakathon.configuration import DiagnosisMap, validate_analysis_config, validate_baseline_config
from rakathon.data.normalization import patient_core
from rakathon.domain import (
    FEATURE_SCHEMA_VERSION,
    METHOD_VERSION,
    AnalysisConfig,
    AnalysisResult,
    BaselineConfig,
    BaselineResult,
    DatasetBundle,
    SourceMode,
)
from rakathon.features.catalog import descriptor_columns, feature_label, outcome_spec
from rakathon.features.episodes import (
    compute_outcomes,
    episode_context,
    find_anchors,
    select_outcome_episodes,
)
from rakathon.features.laboratories import lab_patient_summary, lab_test_catalog, lab_test_patient_medians
from rakathon.features.patient_table import build_patient_table
from rakathon.models.base import get_baseline_model


def now_iso() -> str:
    return datetime.now(UTC).strftime("%Y-%m-%dT%H:%M:%SZ")


def run_environment() -> dict[str, str]:
    env = {"python": platform.python_version()}
    for pkg in ("pandas", "numpy", "scikit-learn", "streamlit", "plotly"):
        try:
            env[pkg] = metadata.version(pkg)
        except metadata.PackageNotFoundError:
            env[pkg] = "n/a"
    return env


@dataclass
class GlobalResults:
    dataset_fingerprint: str
    source_mode: SourceMode
    source_label: str
    baseline: BaselineResult
    results_long: pd.DataFrame  # pacient × ukazatel: observed, expected, residual, log_residual, stavy
    outcomes_long: pd.DataFrame
    selected_episodes: pd.DataFrame
    core: pd.DataFrame
    patient_table: pd.DataFrame
    lab_medians: pd.DataFrame
    lab_catalog: pd.DataFrame
    extra_meta: pd.DataFrame | None
    metric_labels: dict[str, str] = field(default_factory=dict)
    metric_long_labels: dict[str, str] = field(default_factory=dict)

    @property
    def baseline_config_id(self) -> str:
        return self.baseline.config_id

    def label(self, col: str) -> str:
        return feature_label(col, self.extra_meta)


def compute_global(bundle: DatasetBundle, config: BaselineConfig, dxmap: DiagnosisMap) -> GlobalResults:
    validate_baseline_config(config)
    core = patient_core(bundle.patients)
    selected = select_outcome_episodes(bundle.episodes, core, config.episode_rule, dxmap)
    anchors = find_anchors(bundle.episodes, core)
    outcomes = compute_outcomes(selected, core, config.episode_rule, anchors, config.outcomes)
    context = episode_context(bundle.episodes, core, selected, anchors)
    lab_summary = lab_patient_summary(bundle.labs)
    table = build_patient_table(core, context, lab_summary, bundle.extra)

    model = get_baseline_model(config.method)
    baseline_long = model.predict(core, outcomes, config)
    results = attach_residuals(baseline_long, outcomes)
    generated = now_iso()
    baseline = BaselineResult(
        table=results,
        config=config,
        dataset_fingerprint=bundle.fingerprint,
        source_mode=bundle.source_mode,
        generated_at=generated,
        meta={
            "method_label": model.label,
            "feature_schema_version": FEATURE_SCHEMA_VERSION,
            "method_version": METHOD_VERSION,
            "environment": run_environment(),
            "n_patients": int(len(core)),
        },
    )
    specs = {m: outcome_spec(m, config.episode_rule) for m in config.outcomes}
    return GlobalResults(
        dataset_fingerprint=bundle.fingerprint,
        source_mode=bundle.source_mode,
        source_label=bundle.source_label,
        baseline=baseline,
        results_long=results,
        outcomes_long=outcomes,
        selected_episodes=selected,
        core=core,
        patient_table=table,
        lab_medians=lab_test_patient_medians(bundle.labs),
        lab_catalog=lab_test_catalog(bundle.labs),
        extra_meta=bundle.extra_meta,
        metric_labels={m: s.short_label for m, s in specs.items()},
        metric_long_labels={m: s.label for m, s in specs.items()},
    )


def compute_analysis(g: GlobalResults, config: AnalysisConfig) -> AnalysisResult:
    validate_analysis_config(config)
    unknown = [m for m in config.metrics if m not in g.baseline.config.outcomes]
    if unknown:
        raise ValueError(f"Ukazatele {unknown} nejsou součástí aktivní globální baseline.")
    det = run_robust_detector(g.results_long, config)
    scores, dims = det["scores"], det["dims"]
    clusters, info = cluster_outliers(scores, dims, config)
    scores = scores.merge(
        clusters[["patient_id", "cluster_id", "cluster_label"]],
        on="patient_id",
        how="left",
        validate="one_to_one",
    )
    scores["cluster_label"] = scores["cluster_label"].fillna("")
    cat_cols, num_cols = descriptor_columns(g.extra_meta)
    group_summary, cards = describe_groups(
        clusters,
        scores,
        dims,
        g.patient_table,
        det["reference_ids"],
        cat_cols,
        num_cols,
        g.lab_medians,
        g.label,
        g.metric_labels,
    )
    return AnalysisResult(
        analysis_id=config.analysis_id(g.dataset_fingerprint, g.baseline_config_id),
        config=config,
        baseline_config_id=g.baseline_config_id,
        dataset_fingerprint=g.dataset_fingerprint,
        source_mode=g.source_mode,
        generated_at=now_iso(),
        scores=scores,
        dims=dims,
        calibration=det["calibration"],
        clusters=clusters,
        cluster_info=info,
        group_summary=group_summary,
        group_cards=cards,
        reference_ids=det["reference_ids"],
        meta={"method_version": METHOD_VERSION, "environment": run_environment()},
    )
