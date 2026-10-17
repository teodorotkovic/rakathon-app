"""Shlukování POUZE uvnitř množiny neobvyklých pacientů (volitelně i těsně pod hranicí).

Uživatel volí algoritmus (hierarchické shlukování nebo k-means), proměnné a počet shluků (automaticky podle
siluety, nebo ručně). Proměnné se převádějí na společnou škálu „kolik běžných rozptylů od mediánu
porovnatelných pacientů“ (robustní standardizace), aby dny, počty a míra odchylky měly srovnatelnou váhu.
Nic se nedoplňuje: pacient bez hodnoty některé zvolené proměnné se vyřadí a vypíše.

Modul neimportuje Streamlit. Výstup používá pipeline (štítky, popis skupin, export) i UI (vizualizace).
"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass, field

import numpy as np
import pandas as pd
from scipy.cluster.hierarchy import fcluster, leaves_list, linkage
from sklearn.cluster import KMeans
from sklearn.decomposition import PCA
from sklearn.metrics import silhouette_samples, silhouette_score

from rakathon.analysis.detectors import BAND_NEAR, robust_scale
from rakathon.domain import AnalysisConfig

PLAIN_METRIC = {"median_los_dx": "typický pobyt", "max_los_dx": "nejdelší pobyt"}
AUTO_K_MAX = 6
MANUAL_K_MAX = 8
METHOD_LABELS = {"hierarchical": "hierarchické shlukování", "kmeans": "k-means"}
LINKAGE_LABELS = {"ward": "Ward", "average": "průměrná vzdálenost", "complete": "nejvzdálenější body"}

LabelFn = Callable[[str], str]


@dataclass
class ClusteringOutput:
    assignments: pd.DataFrame  # patient_id, cluster_id (Int64), cluster_label, isolated
    info: dict
    matrix: pd.DataFrame = field(
        default_factory=pd.DataFrame
    )  # standardizované hodnoty shlukovaných pacientů
    raw: pd.DataFrame = field(default_factory=pd.DataFrame)  # původní jednotky, všichni porovnatelní pacienti
    linkage: np.ndarray | None = None
    features: list[dict] = field(default_factory=list)


# ---------------------------------------------------------------------------
# Proměnné
# ---------------------------------------------------------------------------


def default_feature_keys(metrics: tuple[str, ...] | list[str]) -> list[str]:
    return [f"z:{m}" for m in metrics]


def feature_options(
    metrics: tuple[str, ...] | list[str],
    numeric_columns: list[str],
    patient_table: pd.DataFrame,
    label_fn: LabelFn,
) -> dict[str, str]:
    """Klíč proměnné → srozumitelný popisek. Jen číselné údaje (jedna hodnota na pacienta)."""
    opts: dict[str, str] = {}
    for m in metrics:
        opts[f"z:{m}"] = f"Míra odchylky – {PLAIN_METRIC.get(m, m)} (+ delší, − kratší)"
    for m in metrics:
        opts[f"res:{m}"] = f"Rozdíl oproti očekávání – {PLAIN_METRIC.get(m, m)} (dny)"
    opts["other_stays"] = "Hospitalizace s jinou hlavní diagnózou (počet)"
    opts["age"] = "Věková skupina (pořadí)"
    for c in numeric_columns:
        if c in patient_table.columns:
            opts[f"pt:{c}"] = label_fn(c)
    return opts


def feature_unit(key: str) -> str:
    if key.startswith("z:"):
        return "násobky běžného rozptylu"
    if key.startswith("res:"):
        return "dny"
    if key == "age":
        return "pořadí skupiny"
    return ""


def feature_values(key: str, dims: pd.DataFrame, patient_table: pd.DataFrame) -> pd.Series:
    """Hodnota proměnné v původních jednotkách, index = patient_id."""
    t = patient_table.set_index("patient_id")
    if key.startswith(("z:", "res:")):
        kind, metric = key.split(":", 1)
        col = "z" if kind == "z" else "residual"
        d = dims[dims["metric_id"] == metric].set_index("patient_id")[col]
        return pd.to_numeric(d, errors="coerce").astype(float).reindex(t.index)
    if key == "age":
        return pd.to_numeric(t["age_order"], errors="coerce").astype(float)
    if key == "other_stays":
        return (t["n_inpatient_completed"] - t["n_stays_included"]).astype(float)
    if key.startswith("pt:"):
        return pd.to_numeric(t[key[3:]], errors="coerce").astype(float)
    raise KeyError(f"Neznámá proměnná pro shlukování: {key}")


# ---------------------------------------------------------------------------
# Shlukování
# ---------------------------------------------------------------------------


def _members(scores: pd.DataFrame, include_near: bool) -> list[str]:
    s = scores[scores["scored"].astype(bool)]
    mask = s["outlier"].astype(bool)
    if include_near:
        mask |= s["band"] == BAND_NEAR
    return s.loc[mask].sort_values(["score", "patient_id"], ascending=[False, True])["patient_id"].tolist()


def _fit(X: np.ndarray, k: int, config: AnalysisConfig, Z: np.ndarray | None) -> np.ndarray:
    if config.cluster_method == "kmeans":
        return KMeans(n_clusters=k, n_init=10, random_state=0).fit_predict(X)
    return fcluster(Z, k, criterion="maxclust") - 1


def _silhouette(X: np.ndarray, labels: np.ndarray) -> float:
    n_labels = len(set(labels))
    if n_labels < 2 or n_labels >= len(labels):
        return float("nan")
    return float(silhouette_score(X, labels))


def silhouette_words(value: float) -> str:
    if value is None or np.isnan(value):
        return "oddělení nelze posoudit"
    if value >= 0.5:
        return "shluky jsou jasně oddělené"
    if value >= 0.25:
        return "shluky jsou částečně oddělené"
    return "shluky jsou oddělené jen slabě – vzorec může být náhodný"


def cluster_outliers(
    scores: pd.DataFrame,
    dims: pd.DataFrame,
    patient_table: pd.DataFrame,
    config: AnalysisConfig,
    label_fn: LabelFn | None = None,
) -> ClusteringOutput:
    label_fn = label_fn or (lambda c: c)
    empty = pd.DataFrame(columns=["patient_id", "cluster_id", "cluster_label", "isolated"])
    members = _members(scores, config.cluster_include_near)
    info: dict = {
        "status": "",
        "message": "",
        "method": config.cluster_method,
        "linkage": config.cluster_linkage,
        "n_outliers": int(scores["outlier"].astype(bool).sum()),
        "n_members": len(members),
        "include_near": config.cluster_include_near,
        "n_groups": 0,
    }
    if not members:
        info.update(status="no_outliers", message="Při aktuální hranici nejsou žádní neobvyklí pacienti.")
        return ClusteringOutput(empty, info)

    # --- proměnné a standardizace vůči porovnatelným pacientům ---
    requested = (
        list(config.cluster_features) if config.cluster_features else default_feature_keys(config.metrics)
    )
    scored_ids = scores.loc[scores["scored"].astype(bool), "patient_id"].tolist()
    raw_cols, std_cols, feats, dropped = {}, {}, [], []
    for key in requested:
        if key.startswith(("z:", "res:")) and key.split(":", 1)[1] not in config.metrics:
            dropped.append((key, "ukazatel není v aktuálním porovnání"))
            continue
        try:
            values = feature_values(key, dims, patient_table)
        except KeyError:
            dropped.append((key, "proměnná neexistuje"))
            continue
        ref = values.reindex(scored_ids).to_numpy(dtype=float)
        if key.startswith("z:"):
            center, scale = 0.0, 1.0  # míra odchylky už je v násobcích běžného rozptylu
        else:
            center, scale, _ = robust_scale(ref)
        if np.isnan(scale):
            dropped.append((key, "u porovnatelných pacientů nemá rozptyl"))
            continue
        raw_cols[key] = values
        std_cols[key] = (values - center) / scale
        feats.append(
            {"key": key, "label": label_fn(key), "unit": feature_unit(key), "center": center, "scale": scale}
        )
    info["dropped_features"] = dropped
    info["features"] = [f["key"] for f in feats]
    info["one_dimensional"] = len(feats) == 1
    single_rows = [
        {"patient_id": p, "cluster_id": pd.NA, "cluster_label": "jednotlivý případ", "isolated": True}
        for p in members
    ]
    if not feats:
        info.update(status="no_features", message="Žádná ze zvolených proměnných nejde použít.")
        return ClusteringOutput(pd.DataFrame(single_rows), info)
    raw = pd.DataFrame(raw_cols).reindex(scored_ids)
    std_all = pd.DataFrame(std_cols).reindex(scored_ids)
    matrix = std_all.reindex(members)
    excluded = matrix.index[matrix.isna().any(axis=1)].tolist()
    matrix = matrix.dropna()
    info["excluded"] = excluded
    n = len(matrix)
    info["n_clustered"] = n
    if n < config.cluster_min_outliers:
        extra = f" ({len(excluded)} vyřazeno pro chybějící hodnoty)" if excluded else ""
        info.update(
            status="too_few",
            message=(
                f"Na shlukování je pacientů málo ({n}{extra}; potřeba alespoň {config.cluster_min_outliers}). "
                "Každý je jednotlivý případ – zkuste mírnější hranici nebo přidat pacienty těsně pod hranicí."
            ),
        )
        return ClusteringOutput(pd.DataFrame(single_rows), info, matrix, raw, None, feats)
    X = matrix.to_numpy(dtype=float)
    if np.allclose(X, X[0]):
        info.update(
            status="no_structure", message="Vybraní pacienti mají ve zvolených proměnných stejné hodnoty."
        )
        return ClusteringOutput(pd.DataFrame(single_rows), info, matrix, raw, None, feats)

    Z = (
        linkage(X, method=config.cluster_linkage, metric="euclidean")
        if config.cluster_method == "hierarchical"
        else None
    )
    # --- počet shluků: návrh podle siluety (vždy), použití podle nastavení ---
    candidates = list(range(2, min(AUTO_K_MAX, n - 1) + 1))
    sil_by_k = {k: _silhouette(X, _fit(X, k, config, Z)) for k in candidates}
    valid = {k: v for k, v in sil_by_k.items() if not np.isnan(v)}
    k_suggested = max(valid, key=lambda k: (round(valid[k], 6), -k)) if valid else 2
    k = k_suggested if config.cluster_k is None else max(2, min(int(config.cluster_k), n - 1))
    labels = _fit(X, k, config, Z)

    # --- přečíslování podle velikosti (Shluk 1 = největší) ---
    lab = pd.Series(labels, index=matrix.index)
    sizes = lab.value_counts()
    order = sorted(sizes.index, key=lambda c: (-sizes[c], min(lab.index[lab == c])))
    mapping = {c: i + 1 for i, c in enumerate(order)}
    cid = lab.map(mapping)
    sil_samples = silhouette_samples(X, labels) if 2 <= len(sizes) < n else np.full(n, np.nan)
    sil_by_cluster = pd.Series(sil_samples, index=matrix.index).groupby(cid).mean().to_dict()
    rows = []
    for pid in members:
        if pid in cid.index:
            c = int(cid[pid])
            rows.append(
                {
                    "patient_id": pid,
                    "cluster_id": c,
                    "cluster_label": f"Shluk {c}",
                    "isolated": bool(sizes[order[c - 1]] == 1),
                }
            )
        else:
            rows.append(
                {
                    "patient_id": pid,
                    "cluster_id": pd.NA,
                    "cluster_label": "vyřazen (chybí hodnota)",
                    "isolated": True,
                }
            )
    assignments = pd.DataFrame(rows)
    assignments["cluster_id"] = assignments["cluster_id"].astype("Int64")

    cut = None
    if Z is not None and 1 <= n - k < n - 1:
        cut = float((Z[n - k - 1, 2] + Z[n - k, 2]) / 2)
    silhouette = _silhouette(X, labels)
    n_groups = int((sizes >= 2).sum())
    k_n = len(sizes)
    k_word = "shluk" if k_n == 1 else "shluky" if 2 <= k_n <= 4 else "shluků"
    msg = (
        f"{n} pacientů → {k_n} {k_word} ({METHOD_LABELS[config.cluster_method]}, počet "
        f"{'zvolen automaticky' if config.cluster_k is None else 'zadán ručně'}); {silhouette_words(silhouette)}."
    )
    if info["one_dimensional"]:
        msg += " Shlukuje se podle jediné proměnné: shluky vyjadřují hlavně její výši (u míry odchylky směr a velikost)."
    info.update(
        status="clustered",
        message=msg,
        k=int(len(sizes)),
        k_suggested=int(k_suggested),
        auto_k=config.cluster_k is None,
        silhouette=silhouette,
        silhouette_by_k=sil_by_k,
        silhouette_by_cluster={int(k_): float(v) for k_, v in sil_by_cluster.items()},
        cut_height=cut,
        n_groups=n_groups,
    )
    return ClusteringOutput(assignments, info, matrix, raw, Z, feats)


# ---------------------------------------------------------------------------
# Interpretace a podklady pro vizualizace (čisté funkce)
# ---------------------------------------------------------------------------


def cluster_profile(
    matrix: pd.DataFrame, raw: pd.DataFrame, assignments: pd.DataFrame, features: list[dict]
) -> pd.DataFrame:
    """Shluk × proměnná: medián ve shluku, u všech shlukovaných a u porovnatelných pacientů + standardizovaný
    rozdíl průměru shluku od průměru všech shlukovaných (čím větší |rozdíl|, tím víc proměnná shluk definuje)."""
    a = assignments.dropna(subset=["cluster_id"]).set_index("patient_id")["cluster_id"].astype(int)
    a = a[a.index.isin(matrix.index)]
    rows = []
    for c in sorted(a.unique()):
        ids = a.index[a == c]
        for f in features:
            k = f["key"]
            rows.append(
                {
                    "cluster_id": int(c),
                    "key": k,
                    "label": f["label"],
                    "unit": f["unit"],
                    "cluster_median": float(raw.loc[ids, k].median()),
                    "clustered_median": float(raw.loc[matrix.index, k].median()),
                    "cohort_median": float(raw[k].median()),
                    "std_diff": float(matrix.loc[ids, k].mean() - matrix[k].mean()),
                }
            )
    return pd.DataFrame(
        rows,
        columns=[
            "cluster_id",
            "key",
            "label",
            "unit",
            "cluster_median",
            "clustered_median",
            "cohort_median",
            "std_diff",
        ],
    )


def dendrogram_segments(
    Z: np.ndarray, leaf_ids: list[str], leaf_cluster: dict[str, int]
) -> tuple[list[dict], list[str]]:
    """U-tvary dendrogramu. Každé spojení = jeden segment; barva = shluk, pokud všechny listy pod ním do něj patří."""
    n = len(leaf_ids)
    order = list(leaves_list(Z))
    x_of = {leaf: float(i) for i, leaf in enumerate(order)}
    y_of = {leaf: 0.0 for leaf in range(n)}
    members: dict[int, set[int]] = {leaf: {leaf} for leaf in range(n)}
    segments = []
    for i, (a, b, h, _) in enumerate(Z):
        a, b, node = int(a), int(b), n + i
        members[node] = members[a] | members[b]
        x_of[node] = (x_of[a] + x_of[b]) / 2
        y_of[node] = float(h)
        clusters = {leaf_cluster.get(leaf_ids[m]) for m in members[node]}
        segments.append(
            {
                "x": [x_of[a], x_of[a], x_of[b], x_of[b]],
                "y": [y_of[a], float(h), float(h), y_of[b]],
                "cluster": next(iter(clusters)) if len(clusters) == 1 else None,
                "height": float(h),
                "n": len(members[node]),
            }
        )
    return segments, [leaf_ids[i] for i in order]


def projection_2d(matrix: pd.DataFrame, context: pd.DataFrame | None = None) -> dict:
    """2D projekce PCA (jen pro orientaci): fit na shlukovaných, ostatní porovnatelní se jen promítnou."""
    pca = PCA(n_components=2, random_state=0).fit(matrix.to_numpy(dtype=float))
    out = {
        "members": pd.DataFrame(
            pca.transform(matrix.to_numpy(dtype=float)), index=matrix.index, columns=["pc1", "pc2"]
        ),
        "explained": pca.explained_variance_ratio_.tolist(),
        "loadings": pd.DataFrame(pca.components_.T, index=matrix.columns, columns=["pc1", "pc2"]),
        "context": None,
    }
    if context is not None and len(context):
        ctx = context.dropna()
        if len(ctx):
            out["context"] = pd.DataFrame(
                pca.transform(ctx.to_numpy(dtype=float)), index=ctx.index, columns=["pc1", "pc2"]
            )
    return out
