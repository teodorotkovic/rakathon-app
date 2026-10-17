"""Čisté pomocné funkce UI: klik do buňky → pacient, spolehlivost srovnání, srozumitelný popis."""

import pandas as pd

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


def test_plain_context_follows_settings():
    peer = plain_context("peer_median", "exact_dx_match", "median_los_dx")
    assert "podobnými pacienty" in peer and "kvůli nádoru" in peer
    model = plain_context("ridge_loo", "from_anchor_all_inpatient", "median_los_dx")
    assert "statistického modelu" in model and "od prvního záznamu nádoru" in model
