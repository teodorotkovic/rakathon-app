"""UI smoke průchod přes Streamlit AppTest (syntetická CSV podstrčená jako lokální adresář dat).

Ověřuje: otevření aplikace → detail pacienta → uložení posouzení → přechod do analýzy →
změna ukazatelů a prahu → návrat do detailu → posouzení přežije nový běh.
Nepokrývá gesta v grafech (lasso/box) – ta jsou v manuálním checklistu docs/demo.md.
"""

from pathlib import Path

import pytest
import streamlit as st
from streamlit.testing.v1 import AppTest
from synthetic_data import generate_synthetic

from rakathon.data.io import TABLE_FILES
from rakathon.storage.csv_store import CsvStore

APP = Path(__file__).resolve().parents[1] / "app.py"


@pytest.fixture
def app(tmp_path, monkeypatch):
    data_dir = tmp_path / "data"
    data_dir.mkdir()
    for name, content in generate_synthetic().files.items():
        (data_dir / TABLE_FILES[name]).write_bytes(content)
    runtime = tmp_path / "runtime"
    monkeypatch.setenv("RAKATHON_DATA_DIR", str(data_dir))
    monkeypatch.setenv("RAKATHON_RUNTIME_DIR", str(runtime))
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
    assert not any("Syntetick" in w.value for w in at.warning)
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

    runtime = tmp_path / "runtime"
    stores = list(runtime.glob("real/*/reviews.csv"))
    assert len(stores) == 1
    fp_dir = stores[0].parent
    reviews = CsvStore(
        runtime,
        "real",
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

    next(b for b in at.sidebar.button if b.label == "Jak počítáme očekávání").click().run()
    assert any(c.label.startswith("Podobní pacienti") and c.value for c in at.checkbox)
    next(c for c in at.checkbox if c.label.startswith("Statistický model")).check().run()
    # volby metody jsou vzájemně výlučné
    assert not next(c for c in at.checkbox if c.label.startswith("Podobní pacienti")).value
    _button(at, "Přepočítat očekávání").click().run()
    assert not at.exception, [e.value for e in at.exception]
    assert not any(c.label.startswith("Statistický model") for c in at.checkbox)  # dialog zavřen
    new_id = next(c.value for c in at.caption if "globální očekávání" in c.value)
    assert new_id != old_id
    assert any("Rozklad predikce modelu" in c.value for c in at.caption)
    # posouzení z předchozího kontextu není aktuální, jen v historii
    assert any("Neposouzeno" in m.value for m in at.markdown if "Aktuální posouzení" in m.value)
    assert any("1 jinde" in e.label for e in at.expander)


def test_sidebar_is_simple(app):
    at = app
    sidebar_text = " ".join(
        [c.value for c in at.sidebar.caption]
        + [m.value for m in at.sidebar.markdown]
        + [s.value for s in at.sidebar.success]
    )
    for hidden in ("Skutečná data", "otisk", "Kde leží data", "Kvalita dat", "Nahrané soubory"):
        assert hidden not in sidebar_text
    assert not at.sidebar.expander
    assert any("pacientů" in c.value and "epizod" in c.value for c in at.sidebar.caption)
    labels = [b.label for b in at.sidebar.button]
    assert {"Data a import", "Jak počítáme očekávání", "Doplňkové vlastnosti"} <= set(labels)

    # testovací CSV obsahují upozornění (více nádorů, neplatný interval) → zjednodušený přehled
    warn = next(b for b in at.sidebar.button if b.label.startswith("Upozornění k datům"))
    warn.click().run()
    assert not at.exception, [e.value for e in at.exception]
    text = " ".join(m.value for m in at.markdown)
    assert "více nádorů" in text and "konec dříve než začátek" in text
    assert "multi_tumor" not in text and "day_end" not in text


def test_import_dialog_opens(app):
    at = app
    next(b for b in at.sidebar.button if b.label == "Data a import").click().run()
    assert not at.exception, [e.value for e in at.exception]
    assert any(b.label == "Načíst lokální data" for b in at.button)


def test_reset_view_restores_defaults(app):
    at = app
    at.switch_page("views/deviations.py").run()
    at.slider(key="dv_threshold").set_value(4.0).run()
    _button(at, "Výchozí pohled").click().run()
    assert not at.exception, [e.value for e in at.exception]
    assert at.slider(key="dv_threshold").value == 2.5


def test_without_data_shows_error_not_synthetic(tmp_path, monkeypatch):
    monkeypatch.setenv("RAKATHON_DATA_DIR", str(tmp_path / "missing"))
    monkeypatch.setenv("RAKATHON_RUNTIME_DIR", str(tmp_path / "runtime"))
    st.cache_data.clear()
    st.cache_resource.clear()
    at = AppTest.from_file(str(APP), default_timeout=60)
    at.run()
    assert not at.exception, [e.value for e in at.exception]
    assert at.title[0].value == "Chybí data"
    assert not any(m.label == "Hodnoceno" for m in at.metric)
