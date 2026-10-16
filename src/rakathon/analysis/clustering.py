"""Shlukování POUZE uvnitř množiny označených outlierů.

Aglomerativní shlukování (average linkage) nad podepsanými z-profily zvolených
ukazatelů. Skupiny se nevynucují: při malém počtu outlierů se vrací jednotlivé
případy, singletony zůstávají „izolovanými případy“. U jedné dimenze skupiny
vyjadřují hlavně směr a velikost odchylky – to se uvádí ve zprávě.
"""

from __future__ import annotations

import numpy as np
import pandas as pd
from sklearn.cluster import AgglomerativeClustering

from rakathon.domain import AnalysisConfig


def cluster_outliers(
    scores: pd.DataFrame, dims: pd.DataFrame, config: AnalysisConfig
) -> tuple[pd.DataFrame, dict]:
    outliers = scores.loc[scores["outlier"].astype(bool), "patient_id"].tolist()
    std_metrics = sorted(
        dims.loc[dims["standardizable"], "metric_id"].unique(), key=list(config.metrics).index
    )
    empty = pd.DataFrame(columns=["patient_id", "cluster_id", "cluster_label", "isolated"])
    info: dict = {
        "n_outliers": len(outliers),
        "n_dimensions": len(std_metrics),
        "status": "",
        "message": "",
        "one_dimensional": len(std_metrics) == 1,
    }
    if len(outliers) == 0:
        info.update(status="no_outliers", message="Při aktuálním prahu není označen žádný outlier.")
        return empty, info
    if len(outliers) < config.cluster_min_outliers:
        info.update(
            status="too_few",
            message=(
                f"Příliš málo případů pro skupinový vzorec ({len(outliers)} < "
                f"{config.cluster_min_outliers}); zobrazeny jsou jednotlivé případy."
            ),
        )
        rows = [
            {"patient_id": p, "cluster_id": pd.NA, "cluster_label": "jednotlivý případ", "isolated": True}
            for p in outliers
        ]
        return pd.DataFrame(rows), info

    X = (
        dims[dims["patient_id"].isin(outliers) & dims["metric_id"].isin(std_metrics)]
        .pivot(index="patient_id", columns="metric_id", values="z")
        .reindex(index=outliers, columns=std_metrics)
        .to_numpy(dtype=float)
    )
    if np.isnan(X).any():
        raise AssertionError("Outlier musí mít úplný profil standardizovaných dimenzí.")
    model = AgglomerativeClustering(
        n_clusters=None, distance_threshold=config.cluster_distance_threshold, linkage="average"
    )
    labels = model.fit_predict(X)
    lab = pd.Series(labels, index=outliers)
    sizes = lab.value_counts()
    multi = [c for c in sizes.index if sizes[c] >= 2]
    # Stabilní pořadí: větší skupiny první, pak podle nejmenšího ID.
    multi.sort(key=lambda c: (-sizes[c], min(lab.index[lab == c])))
    mapping = {c: i + 1 for i, c in enumerate(multi)}
    rows = []
    for pid in outliers:
        c = lab[pid]
        if c in mapping:
            rows.append(
                {
                    "patient_id": pid,
                    "cluster_id": mapping[c],
                    "cluster_label": f"Skupina {mapping[c]}",
                    "isolated": False,
                }
            )
        else:
            rows.append(
                {
                    "patient_id": pid,
                    "cluster_id": pd.NA,
                    "cluster_label": "izolovaný případ",
                    "isolated": True,
                }
            )
    out = pd.DataFrame(rows)
    out["cluster_id"] = out["cluster_id"].astype("Int64")
    n_groups = len(mapping)
    msg = (
        f"{len(outliers)} outlierů → {n_groups} skupin(y) a {int(out['isolated'].sum())} izolovaných případů."
    )
    if info["one_dimensional"]:
        msg += " Analýza má jednu dimenzi: skupiny vyjadřují hlavně směr a velikost odchylky."
    if n_groups == 0:
        msg += " Žádný opakující se vzorec mezi outliery nebyl nalezen."
    info.update(status="clustered", message=msg, n_groups=n_groups)
    return out, info
