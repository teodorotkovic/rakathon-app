"""Sestavení exportních tabulek a ZIP balíčku.

Export reprodukuje aktuálně zobrazený pohled: stejné pacienty ve stejném pořadí a
konfiguraci, ze které vznikl. Uživatelské textové buňky se pro Excel chrání proti
spuštění vzorců (prefix apostrofem) – jen v textových sloupcích, ne u čísel a ID.
Kanonické úložiště (reviews.csv v runtime/) zůstává věrné vstupu.
"""

from __future__ import annotations

import io
import json
import zipfile

import pandas as pd

from rakathon.domain import (
    FEATURE_SCHEMA_VERSION,
    METHOD_VERSION,
    AnalysisResult,
    canonical_json,
    review_label,
)
from rakathon.pipeline import GlobalResults

FORMULA_PREFIXES = ("=", "+", "-", "@", "\t", "\r")


def excel_safe(df: pd.DataFrame, text_columns: list[str]) -> pd.DataFrame:
    out = df.copy()
    for col in text_columns:
        if col not in out.columns:
            continue
        out[col] = out[col].map(
            lambda v: "'" + v if isinstance(v, str) and v.startswith(FORMULA_PREFIXES) else v
        )
    return out


def _identity(g: GlobalResults, a: AnalysisResult | None) -> dict[str, str]:
    return {
        "dataset_fingerprint": g.dataset_fingerprint,
        "source_mode": g.source_mode.value,
        "baseline_config_id": g.baseline_config_id,
        "analysis_id": a.analysis_id if a is not None else "",
        "feature_schema_version": FEATURE_SCHEMA_VERSION,
        "method_version": METHOD_VERSION,
    }


def patient_results_table(g: GlobalResults, patient_ids: list[str]) -> pd.DataFrame:
    """Long: pacient × ukazatel. Pořadí pacientů podle patient_ids (= zobrazený pohled)."""
    r = g.results_long[g.results_long["patient_id"].isin(patient_ids)].copy()
    order = {pid: i for i, pid in enumerate(patient_ids)}
    r["_order"] = r["patient_id"].map(order)
    r = r.sort_values(["_order", "metric_id"]).drop(columns="_order")
    r["metric_label"] = r["metric_id"].map(g.metric_long_labels)
    r["unit"] = "dny"
    r["observed_available"] = r["observed"].notna()
    r["expected_available"] = r["expected"].notna()
    for k, v in _identity(g, None).items():
        if k != "analysis_id":
            r[k] = v
    r["generated_at"] = g.baseline.generated_at
    cols = [
        "patient_id",
        "metric_id",
        "metric_label",
        "unit",
        "observed",
        "observed_available",
        "support_n",
        "outcome_status",
        "outcome_reason",
        "expected",
        "expected_available",
        "baseline_status",
        "baseline_reason",
        "residual",
        "log_residual",
        "evaluable",
        "evaluability_reason",
        "reference_level",
        "reference_level_label",
        "factors_used",
        "factors_not_used",
        "reference_n",
        "reference_ids",
        "ref_q1",
        "ref_q3",
        "ref_min",
        "ref_max",
        "population_median",
        "dataset_fingerprint",
        "source_mode",
        "baseline_config_id",
        "feature_schema_version",
        "method_version",
        "generated_at",
    ]
    return r[cols].reset_index(drop=True)


def analysis_results_table(
    g: GlobalResults,
    a: AnalysisResult,
    reviews_current: pd.DataFrame,
    patient_ids: list[str],
    view_label: str,
) -> pd.DataFrame:
    s = a.scores.set_index("patient_id").reindex(patient_ids).reset_index()
    rv = reviews_current.set_index("patient_id") if not reviews_current.empty else pd.DataFrame()
    s["review_status"] = s["patient_id"].map(
        lambda p: review_label(rv.at[p, "status"]) if p in rv.index else review_label("")
    )
    s["review_comment"] = s["patient_id"].map(lambda p: rv.at[p, "comment"] if p in rv.index else "")
    s["reviewer"] = s["patient_id"].map(lambda p: rv.at[p, "reviewer"] if p in rv.index else "")
    s["review_analysis_id"] = s["patient_id"].map(lambda p: rv.at[p, "analysis_id"] if p in rv.index else "")
    s["view"] = view_label
    s["threshold"] = a.config.threshold
    s["metrics"] = ";".join(a.config.metrics)
    s["scale"] = a.config.scale
    for k, v in _identity(g, a).items():
        s[k] = v
    s["generated_at"] = a.generated_at
    cols = [
        "patient_id",
        "rank",
        "scored",
        "not_scored_reason",
        "score",
        "outlier",
        "band",
        "direction",
        "direction_label",
        "driver_metric",
        "support_level",
        "support_notes",
        "sensitivity",
        "cluster_label",
        "in_reference",
        "review_status",
        "review_comment",
        "reviewer",
        "review_analysis_id",
        "view",
        "threshold",
        "metrics",
        "scale",
        "dataset_fingerprint",
        "source_mode",
        "baseline_config_id",
        "analysis_id",
        "feature_schema_version",
        "method_version",
        "generated_at",
    ]
    return excel_safe(s[cols], ["review_comment", "reviewer", "view", "not_scored_reason"])


def reviews_export_table(reviews: pd.DataFrame) -> pd.DataFrame:
    out = reviews.copy()
    out["status_label"] = out["status"].map(review_label)
    return excel_safe(out, ["comment", "reviewer", "analysis_label"])


def config_table(g: GlobalResults, a: AnalysisResult | None, view_label: str, filters: dict) -> pd.DataFrame:
    row = {
        **_identity(g, a),
        "view": view_label,
        "baseline_config_json": canonical_json(g.baseline.config.to_dict()),
        "analysis_config_json": canonical_json(a.config.to_dict()) if a is not None else "",
        "filters_json": canonical_json(filters),
        "environment_json": canonical_json(g.baseline.meta.get("environment", {})),
        "generated_at": a.generated_at if a is not None else g.baseline.generated_at,
    }
    return excel_safe(pd.DataFrame([row]), ["view"])


def build_zip(tables: dict[str, pd.DataFrame], metadata: dict) -> bytes:
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w", compression=zipfile.ZIP_DEFLATED) as zf:
        for name, df in tables.items():
            zf.writestr(name, df.to_csv(index=False, lineterminator="\n").encode("utf-8-sig"))
        zf.writestr("metadata.json", json.dumps(metadata, ensure_ascii=False, indent=2, default=str))
        zf.writestr(
            "README.txt",
            (
                "Export z prototypu analýzy odchylek (Rakathon 2026). Výzkumný prototyp, nikoli klinické skóre.\n"
                "patient_results.csv – pozorované a očekávané hodnoty, rezidua, reference (long: pacient × ukazatel)\n"
                "analysis_results.csv – lokální skóre, outlier, skupina a posouzení pro zobrazené pacienty\n"
                "reviews.csv – všechna posouzení k tomuto datasetu včetně historie\n"
                "analysis_config.csv – použitá konfigurace, filtry, verze a otisk datasetu\n"
                "group_summary.csv – popis skupin outlierů vůči referenci (je-li k dispozici)\n"
                "data_quality.csv – zpráva o validaci vstupu\n"
                "Pokud data pocházejí ze skutečné kohorty, nakládejte s exportem jako s pseudonymizovanými daty.\n"
            ).encode(),
        )
    return buf.getvalue()
