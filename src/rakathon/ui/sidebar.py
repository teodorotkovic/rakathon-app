"""Společný postranní panel: jednoduchý přehled dat a tlačítka otevírající velká okna (dialogy).

Panel záměrně neukazuje technické údaje (otisk datasetu, kódy validace, cesty). Otevřený dialog se drží ve
stavu relace (`state.K_DIALOG`), aby přežil i celé přeběhnutí skriptu.
"""

from __future__ import annotations

from dataclasses import replace

import pandas as pd
import streamlit as st

from rakathon.configuration import ConfigError, default_baseline_config, validate_baseline_config
from rakathon.data.io import match_uploaded_files
from rakathon.domain import Severity, SourceMode, ValidationReport
from rakathon.features.extra import (
    ALLOWED_DTYPES,
    apply_meta,
    infer_meta,
    parse_extra,
    validate_extra,
    validate_meta,
)
from rakathon.features.patient_table import reserved_columns
from rakathon.formatting import fmt_days, patients_word
from rakathon.ui import state
from rakathon.ui.texts import METHOD_OPTIONS, RULE_OPTIONS

DIALOG_IMPORT = "import"
DIALOG_SETTINGS = "settings"
DIALOG_EXTRA = "extra"
DIALOG_WARNINGS = "warnings"

SEVERITY_LABELS = {"blocking": "Blokující", "warning": "Upozornění", "info": "Informace"}

# Srozumitelné znění důležitých upozornění k datům (tabulka, kód) → věta pro lékaře.
PLAIN_WARNINGS: dict[tuple[str, str], str] = {
    (
        "patients",
        "multi_tumor",
    ): "Někteří pacienti mají v registru více nádorů – zobrazují se, ale do výpočtu "
    "očekávání nevstupují (není jasné, ke kterému nádoru patří které pobyty).",
    (
        "patients",
        "missing",
    ): "U některých pacientů chybí diagnóza nádoru – nelze je porovnat s podobnými pacienty.",
    ("patients", "enum"): "Některé údaje pacientů mají neznámou hodnotu (např. pohlaví nebo věková skupina).",
    ("patients", "pattern"): "Některé kódy pacientů mají neobvyklý tvar.",
    (
        "episodes",
        "invalid_interval",
    ): "Některé pobyty mají konec dříve než začátek – pro délku pobytu se nepoužijí.",
    ("episodes", "not_integer"): "Některé pobyty mají nečitelné datum konce – pro délku pobytu se nepoužijí.",
    (
        "episodes",
        "unknown_patient",
    ): "Některé pobyty patří pacientům, kteří nejsou v seznamu pacientů – nepoužijí se.",
    ("episodes", "negative"): "Některé pobyty začínají před prvním záznamem pacienta.",
    ("episodes", "pattern"): "Některé diagnózy pobytů mají neobvyklý tvar kódu.",
    ("labs", "unknown_patient"): "Některé laboratorní výsledky patří pacientům mimo seznam – nepoužijí se.",
    (
        "labs",
        "unknown_episode",
    ): "U některých laboratorních výsledků nesedí vazba na pobyt – výsledek zůstává u "
    "pacienta, ale bez vazby na pobyt.",
    (
        "labs",
        "patient_mismatch",
    ): "U některých laboratorních výsledků nesedí vazba na pobyt – výsledek zůstává u "
    "pacienta, ale bez vazby na pobyt.",
    ("labs", "not_numeric"): "Některé laboratorní hodnoty nejsou čísla – v souhrnech se nepoužijí.",
    ("labs", "not_integer"): "Některé laboratorní výsledky nemají den odběru – v časovém průběhu chybí.",
}


# ---------------------------------------------------------------------------
# Postranní panel
# ---------------------------------------------------------------------------


def render() -> None:
    b = state.dataset()
    warnings = important_warnings(b.validation)
    pending = st.session_state.get(state.K_PENDING_EXCL, {})
    with st.sidebar:
        n_pat = b.patients["patient_id"].nunique()
        st.caption(
            f"{n_pat} pacientů · {len(b.episodes):,} epizod · {len(b.labs):,} lab. výsledků".replace(",", " ")
        )
        if warnings:
            st.button(
                f"Upozornění k datům ({len(warnings)})",
                key="sb_warnings",
                icon=":material/warning:",
                width="stretch",
                on_click=state.open_dialog,
                args=(DIALOG_WARNINGS,),
            )
        st.button(
            "Data a import",
            key="sb_import",
            icon=":material/folder_open:",
            width="stretch",
            on_click=state.open_dialog,
            args=(DIALOG_IMPORT,),
        )
        st.button(
            "Jak počítáme očekávání",
            key="sb_settings",
            icon=":material/tune:",
            width="stretch",
            type="primary" if pending else "secondary",
            on_click=_open_settings,
        )
        if pending:
            st.caption(f"Navržené vyřazení ({len(pending)}) čeká na přepočet.")
        st.button(
            "Doplňkové vlastnosti",
            key="sb_extra",
            icon=":material/playlist_add:",
            width="stretch",
            on_click=state.open_dialog,
            args=(DIALOG_EXTRA,),
        )
        st.caption(
            "Výzkumný hackathonový prototyp (Rakathon 2026) – nejde o ověřené klinické skóre ani doporučení léčby."
        )
    _show_open_dialog()


def _show_open_dialog() -> None:
    dialogs = {
        DIALOG_IMPORT: _import_dialog,
        DIALOG_SETTINGS: _settings_dialog,
        DIALOG_EXTRA: _extra_dialog,
        DIALOG_WARNINGS: _warnings_dialog,
    }
    dialog = dialogs.get(st.session_state.get(state.K_DIALOG))
    if dialog is not None:
        dialog()


def important_warnings(report: ValidationReport) -> list[str]:
    """Jen důležitá upozornění (warning/blocking) srozumitelnými větami, bez kódů a sloupců."""
    lines: dict[str, int] = {}
    for issue in report.issues:
        if issue.severity == Severity.INFO:
            continue
        text = PLAIN_WARNINGS.get((issue.table, issue.code), issue.message)
        lines[text] = lines.get(text, 0) + issue.count
    return [f"{text} (týká se {count} záznamů)" for text, count in lines.items()]


# ---------------------------------------------------------------------------
# Dialogy
# ---------------------------------------------------------------------------


@st.dialog("Upozornění k datům", width="large", on_dismiss=state.close_dialog)
def _warnings_dialog() -> None:
    st.markdown("Aplikace s daty pracuje dál, jen s těmito omezeními:")
    for line in important_warnings(state.dataset().validation):
        st.markdown(f"- {line}")


@st.dialog("Data a import", width="large", on_dismiss=state.close_dialog)
def _import_dialog() -> None:
    _import_content()


@st.dialog("Doplňkové vlastnosti pacientů", width="large", on_dismiss=state.close_dialog)
def _extra_dialog() -> None:
    _extra_content()


@st.dialog("Jak počítáme očekávání", width="large", on_dismiss=state.close_dialog)
def _settings_dialog() -> None:
    _settings_content()


# ---------------------------------------------------------------------------
# Data a import (obsah beze změny; používá ho i obrazovka bez dat)
# ---------------------------------------------------------------------------


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


def _import_content() -> None:
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
        state.close_dialog()
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
            state.close_dialog()
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
    _import_content()


# ---------------------------------------------------------------------------
# Jak počítáme očekávání (globální nastavení srozumitelně)
# ---------------------------------------------------------------------------


def _set_choice(group: str, value: str, values: list[str]) -> None:
    ss = st.session_state
    ss[f"gs_{group}"] = value
    for v in values:
        ss[f"gs_{group}_{v}"] = v == value


def _fill_settings(method: str, rule: str, min_ref: int, min_lim: int, keep_excl: list[str]) -> None:
    _set_choice("method", method, list(METHOD_OPTIONS))
    _set_choice("rule", rule, list(RULE_OPTIONS))
    st.session_state["gs_min_ref"] = min_ref
    st.session_state["gs_min_lim"] = min_lim
    st.session_state["gs_keep_excl"] = keep_excl


def _open_settings() -> None:
    cfg = state.baseline_config()
    _fill_settings(
        cfg.method,
        cfg.episode_rule,
        cfg.min_reference,
        cfg.min_limited_reference,
        list(cfg.excluded_patient_ids),
    )
    state.open_dialog(DIALOG_SETTINGS)


def _fill_recommended() -> None:
    d = default_baseline_config(state.settings(), state.dxmap())
    _fill_settings(d.method, d.episode_rule, d.min_reference, d.min_limited_reference, [])


def _on_toggle(group: str, value: str, values: list[str]) -> None:
    if st.session_state[f"gs_{group}_{value}"]:
        _set_choice(group, value, values)
    else:  # vybranou možnost nelze odškrtnout – vždy platí právě jedna
        st.session_state[f"gs_{group}_{value}"] = True


def _exclusive_choice(group: str, options: dict[str, tuple[str, str, str]], current: str) -> None:
    values = list(options)
    for value, (label, caption, help_text) in options.items():
        st.checkbox(
            label + ("  · nyní používáno" if value == current else ""),
            key=f"gs_{group}_{value}",
            help=help_text,
            on_change=_on_toggle,
            args=(group, value, values),
        )
        st.caption(caption)


def _settings_content() -> None:
    cfg = state.baseline_config()
    pending = st.session_state.get(state.K_PENDING_EXCL, {})
    if "gs_method" not in st.session_state:  # dialog otevřen jinak než tlačítkem
        _open_settings()
    st.markdown(
        "Pro každého pacienta aplikace odhadne, jak dlouhé pobyty bychom u něj **čekali**, a porovná to se "
        "skutečností – z toho vzniká míra odchylky. Tady volíte, **z čeho** se toto očekávání počítá. "
        "Změna platí pro celou aplikaci; dřívější posouzení lékařů zůstanou uložena v historii."
    )
    st.markdown("##### Metoda odhadu")
    _exclusive_choice("method", METHOD_OPTIONS, cfg.method)
    st.markdown("##### Které hospitalizace počítáme")
    _exclusive_choice("rule", RULE_OPTIONS, cfg.episode_rule)

    if cfg.excluded_patient_ids or pending:
        st.markdown("##### Pacienti vyřazení z výpočtu")
        st.caption(
            "Pacienti s podezřením na chybná data zůstávají v seznamu, ale nevstupují do výpočtu očekávání."
        )
        if cfg.excluded_patient_ids:
            st.multiselect("Ponechat vyřazené", list(cfg.excluded_patient_ids), key="gs_keep_excl")
        if pending:
            st.markdown("**Nově navržená vyřazení:** " + ", ".join(f"{p} ({r})" for p, r in pending.items()))

    with st.expander("Pokročilé"):
        c1, c2 = st.columns(2)
        c1.number_input(
            "Podobných pacientů pro plné srovnání",
            min_value=2,
            max_value=50,
            step=1,
            key="gs_min_ref",
            help="Je-li podobných pacientů méně, srovnání se rozšíří nebo je označeno jako orientační.",
        )
        c2.number_input(
            "Podobných pacientů pro orientační srovnání",
            min_value=1,
            max_value=50,
            step=1,
            key="gs_min_lim",
            help="Při menším počtu se pacient nehodnotí.",
        )
        _accuracy_caption()

    c1, c2 = st.columns(2)
    if c1.button("Přepočítat očekávání", key="gs_apply", type="primary", width="stretch"):
        _apply_settings(cfg, pending)
    c2.button(
        "Obnovit doporučené nastavení",
        key="gs_reset",
        width="stretch",
        on_click=_fill_recommended,
        help="Vyplní doporučené volby; použijí se až po stisku Přepočítat očekávání.",
    )


def _accuracy_caption() -> None:
    g = state.global_results()
    summary = g.baseline.meta.get("oof_summary", [])
    if not summary:
        return
    s = summary[0]
    n = s["n_evaluable"]
    st.caption(
        f"Přesnost aktuálního nastavení: u {n} {patients_word(n)} se skutečný "
        f"{g.metric_labels.get(s['metric_id'], s['metric_id']).lower()} od očekávání typicky liší o "
        f"{fmt_days(s['median_abs_residual_days'])}."
    )


def _apply_settings(cfg, pending: dict[str, str]) -> None:
    ss = st.session_state
    keep_excl = list(ss.get("gs_keep_excl", cfg.excluded_patient_ids))
    reasons = dict(cfg.exclusion_reasons)
    reasons.update(pending)
    excluded = sorted(set(keep_excl) | set(pending))
    new = replace(
        cfg,
        method=ss["gs_method"],
        episode_rule=ss["gs_rule"],
        min_reference=int(ss["gs_min_ref"]),
        min_limited_reference=int(ss["gs_min_lim"]),
        excluded_patient_ids=tuple(excluded),
        exclusion_reasons=tuple(sorted((p, reasons[p]) for p in excluded)),
    )
    try:
        validate_baseline_config(new)
    except ConfigError as exc:
        st.error(str(exc))
        return
    ss[state.K_BASELINE] = new
    ss[state.K_PENDING_EXCL] = {}
    state.flash("success", "Očekávání přepočítáno podle nového nastavení.")
    state.close_dialog()
    st.rerun()


# ---------------------------------------------------------------------------
# Doplňkové vlastnosti (obsah beze změny)
# ---------------------------------------------------------------------------


def _extra_content() -> None:
    b = state.dataset()
    st.caption(
        "Soubor `extra_features.csv`: sloupec `patient_id` + nové sloupce. Vlastnost je jen popisná – "
        "zobrazí se v detailu, filtrech a popisu skupin, ale nevstupuje do očekávání."
    )
    if b.extra_meta is not None:
        st.markdown("**Aktivní:** " + ", ".join(f"{r.label} ({r.dtype})" for r in b.extra_meta.itertuples()))
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
            state.close_dialog()
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
        state.close_dialog()
        st.rerun()
