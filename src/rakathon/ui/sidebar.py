"""Společný postranní panel: aktivní dataset, kvalita dat, import, globální nastavení, doplňkové vlastnosti."""

from __future__ import annotations

from dataclasses import replace

import pandas as pd
import streamlit as st

from rakathon.configuration import ConfigError, default_baseline_config, validate_baseline_config
from rakathon.data.io import match_uploaded_files
from rakathon.domain import Severity, SourceMode, ValidationReport
from rakathon.features.catalog import EPISODE_RULES
from rakathon.features.extra import (
    ALLOWED_DTYPES,
    apply_meta,
    infer_meta,
    parse_extra,
    validate_extra,
    validate_meta,
)
from rakathon.features.patient_table import reserved_columns
from rakathon.formatting import fmt_num
from rakathon.ui import state

SEVERITY_LABELS = {"blocking": "Blokující", "warning": "Upozornění", "info": "Informace"}


def render() -> None:
    with st.sidebar:
        _dataset_box()
        _import_box()
        _global_settings()
        _extra_features()
        _data_locations()


def _report_table(report: ValidationReport) -> pd.DataFrame:
    df = report.to_frame()
    df["severity"] = df["severity"].map(SEVERITY_LABELS)
    return df.rename(
        columns={
            "severity": "Závažnost",
            "table": "Tabulka",
            "column": "Sloupec",
            "code": "Kód",
            "count": "Počet",
            "message": "Popis",
            "examples": "Příklady ID",
        }
    )


def _dataset_box() -> None:
    b = state.dataset()
    st.success("**Skutečná data** (lokálně)", icon=":material/lock:")
    n_pat = b.patients["patient_id"].nunique()
    st.caption(
        f"{b.source_label} · otisk `{b.short_fingerprint}`  \n"
        f"{n_pat} pacientů · {len(b.episodes):,} epizod · {len(b.labs):,} lab. výsledků".replace(",", " ")
    )
    rep = b.validation
    n_warn = len(rep.by_severity(Severity.WARNING))
    n_info = len(rep.by_severity(Severity.INFO))
    with st.expander(f"Kvalita dat: {n_warn} upozornění, {n_info} informací"):
        st.dataframe(_report_table(rep), hide_index=True, width="stretch", height=260)
        st.download_button(
            "Stáhnout zprávu o validaci (CSV)",
            rep.to_frame().to_csv(index=False).encode("utf-8-sig"),
            file_name="data_quality.csv",
            mime="text/csv",
            key="dl_quality",
        )


def _import_box(expanded: bool = False) -> None:
    with st.expander("Zdroj dat / import", expanded=expanded):
        failed = st.session_state.get(state.K_IMPORT_REPORT)
        if failed is not None:
            st.error("Poslední import neprošel validací – aktivní zůstává původní dataset.")
            st.dataframe(_report_table(failed), hide_index=True, width="stretch", height=200)
        s = state.settings()
        st.caption(f"Lokální adresář: `{s.data_dir}`")
        if st.button("Načíst lokální data", key="btn_load_local", width="stretch"):
            ok, rep = state.load_local_dir()
            state.flash(
                "success" if ok else "error",
                "Lokální data načtena."
                if ok
                else f"Lokální data nelze použít: {rep if isinstance(rep, str) else 'validace selhala'}",
            )
            st.rerun()
        uploads = st.file_uploader(
            "Nahrát patients.csv, episodes.csv, labs.csv (najednou)",
            type=["csv"],
            accept_multiple_files=True,
            key=f"upload_dataset_{state.nonce()}",
        )
        if st.button("Ověřit a aktivovat nahraná data", key="btn_upload", disabled=not uploads):
            files, missing = match_uploaded_files({u.name: u.getvalue() for u in uploads})
            if missing:
                st.error(f"Chybí soubory: {', '.join(missing)}. Dataset se aktivuje jen jako celek.")
            else:
                ok, rep = state.activate_files(files, SourceMode.REAL, "Nahrané soubory")
                state.flash(
                    "success" if ok else "error",
                    "Nahraný dataset ověřen a aktivován." if ok else "Nahraný dataset neprošel validací.",
                )
                st.rerun()


def render_no_data() -> None:
    """Obrazovka bez aktivního datasetu: syntetická data aplikace nepoužívá."""
    s = state.settings()
    st.title("Chybí data")
    state.show_flash()
    st.error(
        f"V adresáři `{s.data_dir}` nebyla nalezena platná data (`patients.csv`, `episodes.csv`, `labs.csv`). "
        "Zkopírujte je tam a klikněte na *Načíst lokální data*, nebo je nahrajte níže.",
        icon=":material/folder_off:",
    )
    _import_box(expanded=True)


def _global_settings() -> None:
    cfg = state.baseline_config()
    pending = st.session_state.get(state.K_PENDING_EXCL, {})
    label = "Globální očekávání (pokročilé)" + (" – čeká na přepočet" if pending else "")
    with st.expander(label, expanded=bool(pending)):
        st.caption(
            f"Aktivní konfigurace `{cfg.config_id}`. Změna vytvoří novou verzi výsledků; "
            "dřívější posouzení zůstanou v historii jiného kontextu."
        )
        _oof_caption()
        with st.form(f"global_cfg_{state.nonce()}"):
            methods = list(BASELINE_METHOD_LABELS)
            method = st.selectbox(
                "Metoda očekávání",
                methods,
                index=methods.index(cfg.method),
                format_func=lambda m: BASELINE_METHOD_LABELS[m],
                help="Referenční medián podobných pacientů (výchozí) nebo regrese se stejnými vstupy. "
                "Obě metody počítají očekávání bez vlastního výsledku pacienta.",
            )
            rules = list(EPISODE_RULES)
            rule = st.selectbox(
                "Výběr pobytů pro ukazatel",
                rules,
                index=rules.index(cfg.episode_rule),
                format_func=lambda r: EPISODE_RULES[r]["label"],
                help="Které dokončené hospitalizace vstupují do mediánu/maxima délky pobytu.",
            )
            st.caption(EPISODE_RULES[rule]["limitation"])
            c1, c2 = st.columns(2)
            min_ref = c1.number_input(
                "Plná reference ≥",
                2,
                50,
                cfg.min_reference,
                help="Technická hranice počtu jiných pacientů; není klinicky validovaná.",
            )
            min_lim = c2.number_input("Omezená reference ≥", 1, 50, cfg.min_limited_reference)
            keep_excl = list(cfg.excluded_patient_ids)
            if keep_excl:
                keep_excl = st.multiselect(
                    "Vyřazení pacienti (ponechat vyřazené)", keep_excl, default=keep_excl
                )
            if pending:
                st.markdown("**Navržená vyřazení:** " + ", ".join(f"{p} ({r})" for p, r in pending.items()))
            submitted = st.form_submit_button("Přepočítat očekávání", type="primary")
        if submitted:
            reasons = dict(cfg.exclusion_reasons)
            reasons.update(pending)
            excluded = sorted(set(keep_excl) | set(pending))
            new = replace(
                cfg,
                method=method,
                episode_rule=rule,
                min_reference=int(min_ref),
                min_limited_reference=int(min_lim),
                excluded_patient_ids=tuple(excluded),
                exclusion_reasons=tuple(sorted((p, reasons[p]) for p in excluded)),
            )
            try:
                validate_baseline_config(new)
            except ConfigError as exc:
                st.error(str(exc))
            else:
                st.session_state[state.K_BASELINE] = new
                st.session_state[state.K_PENDING_EXCL] = {}
                state.flash("success", f"Očekávání přepočítáno – nová konfigurace `{new.config_id}`.")
                st.rerun()
        if st.button("Obnovit výchozí globální nastavení", key="btn_reset_global"):
            st.session_state[state.K_BASELINE] = default_baseline_config(state.settings(), state.dxmap())
            st.session_state[state.K_PENDING_EXCL] = {}
            state.flash("info", "Obnoveno výchozí globální očekávání.")
            st.rerun()


BASELINE_METHOD_LABELS = {
    "peer_median": "Referenční medián podobných pacientů (LOO)",
    "ridge_loo": "Ridge regrese nad log1p (dg. kategorie, věk, pohlaví; LOO)",
}


def _oof_caption() -> None:
    g = state.global_results()
    parts = []
    for s in g.baseline.meta.get("oof_summary", []):
        parts.append(
            f"{g.metric_labels.get(s['metric_id'], s['metric_id'])}: hodnoceno {s['n_evaluable']}/{s['n_patients']}, "
            f"medián |rozdílu| {fmt_num(s['median_abs_residual_days'])} d"
        )
    st.caption("Popisné leave-one-out chyby (ne klinická validace): " + "; ".join(parts) + ".")


def _extra_features() -> None:
    b = state.dataset()
    with st.expander("Doplňkové vlastnosti pacientů"):
        st.caption(
            "Soubor `extra_features.csv`: sloupec `patient_id` + nové sloupce. Vlastnost je jen popisná – "
            "zobrazí se v detailu, filtrech a popisu skupin, ale nevstupuje do očekávání."
        )
        if b.extra_meta is not None:
            st.markdown(
                "**Aktivní:** " + ", ".join(f"{r.label} ({r.dtype})" for r in b.extra_meta.itertuples())
            )
            st.download_button(
                "Stáhnout použité doplňkové hodnoty",
                b.extra.to_csv(index=False).encode("utf-8-sig"),
                file_name="extra_features_used.csv",
                key="dl_extra",
            )
            st.download_button(
                "Stáhnout metadata",
                b.extra_meta.to_csv(index=False).encode("utf-8-sig"),
                file_name="extra_features_meta.csv",
                key="dl_extra_meta",
            )
            if st.button("Odebrat doplňkové vlastnosti", key="btn_extra_remove"):
                state.store().delete_extra()
                b.extra, b.extra_meta = None, None
                state.flash("info", "Doplňkové vlastnosti odebrány.")
                st.rerun()
        up = st.file_uploader("Nahrát extra_features.csv", type=["csv"], key=f"upload_extra_{state.nonce()}")
        if up is None:
            return
        try:
            raw = parse_extra(up.getvalue())
        except (UnicodeDecodeError, pd.errors.ParserError, pd.errors.EmptyDataError) as exc:
            st.error(f"Soubor nelze načíst: {exc}")
            return
        g = state.global_results()
        base_cols = [
            c
            for c in g.patient_table.columns
            if b.extra is None or c not in set(b.extra.columns) - {"patient_id"}
        ]
        clean, issues = validate_extra(
            raw, set(g.core["patient_id"]), reserved_columns(g.patient_table[base_cols])
        )
        for i in issues:
            getattr(
                st,
                "error"
                if i.severity == Severity.BLOCKING
                else "warning"
                if i.severity == Severity.WARNING
                else "info",
            )(f"{i.column or ''} {i.message} ({i.count}×)")
        if clean is None:
            return
        st.markdown("Zkontrolujte a případně opravte popis, typ a jednotku:")
        meta = st.data_editor(
            infer_meta(clean),
            key="extra_meta_editor",
            hide_index=True,
            width="stretch",
            disabled=["column", "role"],
            column_config={
                "column": "Sloupec",
                "label": "Popisek",
                "unit": "Jednotka",
                "description": "Popis",
                "dtype": st.column_config.SelectboxColumn("Typ", options=list(ALLOWED_DTYPES), required=True),
                "role": st.column_config.TextColumn("Role", help="V této verzi jen 'descriptor'."),
            },
        )
        if st.button("Uložit a použít doplňkové vlastnosti", key="btn_extra_save", type="primary"):
            problems = validate_meta(meta, clean)
            if problems:
                for p in problems:
                    st.error(f"{p.column}: {p.message}")
                return
            typed, conv = apply_meta(clean, meta)
            for c in conv:
                st.warning(f"{c.column}: {c.message} ({c.count}×)")
            state.store().save_extra(clean, meta)
            b.extra, b.extra_meta = typed, meta
            state.bump_nonce()
            state.flash("success", f"Doplňkové vlastnosti uloženy ({len(meta)} sloupců).")
            st.rerun()


def _data_locations() -> None:
    s = state.settings()
    with st.expander("Kde leží data a výstupy"):
        st.markdown(
            f"- vstupní data: `{s.data_dir}`\n"
            f"- posouzení, pohledy, doplňkové vlastnosti: `{s.runtime_dir}` (podle datasetu)\n"
            "- exporty: tam, kam je uloží prohlížeč\n\n"
            "Po hackathonu tyto složky a stažené exporty smažte. Aplikace nic nemaže automaticky."
        )
