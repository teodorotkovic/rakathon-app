"""Protokol globální baseline a registr metod.

Nová metoda (např. Ridge s LOO/OOF) implementuje BaselineModel.predict a zapíše se
do BASELINE_METHODS. Výstup musí mít sloupce BASELINE_OUTPUT_COLUMNS a očekávání
pacienta nesmí záviset na jeho vlastním pozorovaném výsledku.
"""

from __future__ import annotations

from typing import Protocol

import pandas as pd

from rakathon.domain import BaselineConfig

BASELINE_OUTPUT_COLUMNS = [
    "patient_id",
    "metric_id",
    "expected",
    "baseline_status",
    "baseline_reason",
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
]


class BaselineModel(Protocol):
    method_id: str
    label: str

    def predict(
        self, core: pd.DataFrame, outcomes_long: pd.DataFrame, config: BaselineConfig
    ) -> pd.DataFrame:
        """Vrátí long tabulku (pacient × metrika) se sloupci BASELINE_OUTPUT_COLUMNS."""
        ...


def get_baseline_model(method: str) -> BaselineModel:
    from rakathon.models.peer_median import PeerMedianBaseline

    methods: dict[str, BaselineModel] = {"peer_median": PeerMedianBaseline()}
    if method not in methods:
        raise KeyError(f"Neznámá metoda baseline: {method}")
    return methods[method]
