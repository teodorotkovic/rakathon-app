"""Čisté pomocné funkce UI: klik do buňky → pacient, spolehlivost srovnání, srozumitelný popis."""

import numpy as np
import pandas as pd
import pytest

from rakathon.analysis.explanations import explain_flag
from rakathon.domain import AnalysisConfig
from rakathon.ui.patients import patient_from_cell_selection, reliability_text
from rakathon.ui.texts import plain_context


def test_click_on_any_cell_opens_patient_of_that_row():
    table = pd.DataFrame({"ID": ["P0003", "P0001", "P0002"], "Věk": ["0-5", "6-8", "9-11"]})
    assert patient_from_cell_selection([(1, "Věk")], table) == "P0001"
    assert patient_from_cell_selection([[2, "ID"]], table) == "P0002"
    assert patient_from_cell_selection([], table) is None
    assert patient_from_cell_selection([(7, "ID")], table) is None


def test_reliability_text():
    assert reliability_text(True, "ok", 5, 2) == "✓ dobrá"
    assert reliability_text(True, "limited_reference", 5, 2) == "⚠ omezená (málo podobných pacientů)"
    assert reliability_text(True, "ok", 1, 2) == "⚠ omezená (jen 1 pobyt)"
    assert reliability_text(False, "insufficient_reference", 0, 2).startswith("–")


def test_relative_difference_is_against_expectation_not_log1p():
    """1 den vs. očekávání 3,75 dne = −73,3 % (dříve chybně −57,9 % z log1p)."""
    obs, exp = 1.0, 3.75
    dims = pd.DataFrame(
        [
            {
                "metric_id": "median_los_dx",
                "observed": obs,
                "expected": exp,
                "residual": obs - exp,
                "log_residual": np.log1p(obs) - np.log1p(exp),
                "z": -1.0,
                "is_driver": True,
                "support_n": 7,
                "standardizable": True,
                "allowed_low": np.nan,
                "allowed_high": np.nan,
            }
        ]
    )
    out = explain_flag(
        pd.Series({"scored": False, "not_scored_reason": "test"}),
        dims,
        AnalysisConfig(),
        {"median_los_dx": "Medián délky pobytu"},
    )
    assert out["table"]["Relativní rozdíl"].iloc[0] == pytest.approx(-0.7333, abs=1e-4)


def test_plain_context_follows_settings():
    peer = plain_context("peer_median", "exact_dx_match", "median_los_dx")
    assert "podobnými pacienty" in peer and "kvůli nádoru" in peer
    model = plain_context("ridge_loo", "from_anchor_all_inpatient", "median_los_dx")
    assert "statistického modelu" in model and "od prvního záznamu nádoru" in model
