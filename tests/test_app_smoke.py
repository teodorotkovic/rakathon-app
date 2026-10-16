"""UI smoke průchod přes Streamlit AppTest na syntetických datech.

Ověřuje: otevření aplikace → detail pacienta → uložení posouzení → přechod do analýzy →
změna ukazatelů a prahu → návrat do detailu → posouzení přežije nový běh.
Nepokrývá gesta v grafech (lasso/box) – ta jsou v manuálním checklistu docs/demo.md.
"""

from pathlib import Path

import pytest
import streamlit as st
from streamlit.testing.v1 import AppTest

from rakathon.storage.csv_store import CsvStore

APP = Path(__file__).resolve().parents[1] / "app.py"


@pytest.fixture
def app(tmp_path, monkeypatch):
    monkeypatch.setenv("RAKATHON_SOURCE", "synthetic")
    monkeypatch.setenv("RAKATHON_RUNTIME_DIR", str(tmp_path))
    st.cache_data.clear()
    st.cache_resource.clear()
    at = AppTest.from_file(str(APP), default_timeout=180)
    at.run()
    assert not at.exception, [e.value for e in at.exception]
    return at


def _button(at, label):
    return next(b for b in at.button if b.label == label)


def test_full_doctor_flow(app, tmp_path):
    at = app
    assert at.title[0].value == "Pacienti"
    assert any("Syntetická demonstrační data" in w.value for w in at.warning)
    hodnoceno = next(m for m in at.metric if m.label == "Hodnoceno")
    assert "/" in hodnoceno.value

    pick = at.selectbox(key="pf_pick")
    pid = pick.options[0]
    pick.set_value(pid).run()
    at.button(key="pf_open").click().run()
    assert not at.exception, [e.value for e in at.exception]
    assert at.subheader[0].value == f"Pacient {pid}"
    assert any("S čím pacienta porovnáváme" in m.value for m in at.markdown)

    at.radio[0].set_value("clinically_interesting")
    at.text_area[0].input("Ověřit s mentorem: dlouhé pobyty, „D70“, čárka, nový\nřádek")
    _button(at, "Uložit posouzení").click().run()
    assert not at.exception, [e.value for e in at.exception]
    assert any("Klinicky zajímavé" in m.value for m in at.markdown if "Aktuální posouzení" in m.value)

    at.button(key="detail_to_analysis").click().run()
    assert not at.exception, [e.value for e in at.exception]
    assert at.title[0].value == "Analýza odchylek"
    assert any("Vyšetřovaný výběr (1)" in m.value for m in at.markdown)

    at.pills(key="dv_metrics").set_value(["median_los_dx", "max_los_dx"]).run()
    assert not at.exception, [e.value for e in at.exception]
    at.slider(key="dv_threshold").set_value(3.0).run()
    assert not at.exception, [e.value for e in at.exception]
    info = next(m.value for m in at.markdown if "Skórováno" in m.value)
    assert "nad prahem" in info

    at.button(key="dv_open_detail").click().run()
    assert not at.exception, [e.value for e in at.exception]
    assert at.subheader[0].value == f"Pacient {pid}"
    assert any("Z pohledu" in c.value for c in at.caption)  # lokální skóre označené názvem pohledu

    stores = list(tmp_path.glob("synthetic/*/reviews.csv"))
    assert len(stores) == 1
    fp_dir = stores[0].parent
    reviews = CsvStore(
        tmp_path,
        "synthetic",
        (fp_dir / "dataset.json")
        .read_text(encoding="utf-8")
        .split('"dataset_fingerprint": "')[1]
        .split('"')[0],
    ).load_reviews()
    assert reviews.iloc[-1]["patient_id"] == pid
    assert "nový\nřádek" in reviews.iloc[-1]["comment"]


def test_global_recompute_creates_new_context(app):
    at = app
    pick = at.selectbox(key="pf_pick")
    pid = pick.options[0]
    pick.set_value(pid).run()
    at.button(key="pf_open").click().run()
    _button(at, "Uložit posouzení").click().run()  # posouzení ve výchozím globálním kontextu
    old_id = next(c.value for c in at.caption if "globální očekávání" in c.value)

    method = next(s for s in at.sidebar.selectbox if s.label == "Metoda očekávání")
    method.set_value("ridge_loo")
    next(b for b in at.sidebar.button if b.label == "Přepočítat očekávání").click().run()
    assert not at.exception, [e.value for e in at.exception]
    new_id = next(c.value for c in at.caption if "globální očekávání" in c.value)
    assert new_id != old_id
    assert any("Rozklad predikce modelu" in c.value for c in at.caption)
    # posouzení z předchozího kontextu není aktuální, jen v historii
    assert any("Neposouzeno" in m.value for m in at.markdown if "Aktuální posouzení" in m.value)
    assert any("1 jinde" in e.label for e in at.expander)


def test_reset_view_restores_defaults(app):
    at = app
    at.switch_page("views/deviations.py").run()
    at.slider(key="dv_threshold").set_value(4.0).run()
    _button(at, "Výchozí pohled").click().run()
    assert not at.exception, [e.value for e in at.exception]
    assert at.slider(key="dv_threshold").value == 2.5
