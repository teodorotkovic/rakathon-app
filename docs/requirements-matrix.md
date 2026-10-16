# Matice požadavků

Stav k 2026-10-17. „Hotovo“ = funkční chování ověřené uvedeným způsobem.

## Čtyři povinné výstupy výzvy
| Požadavek | Implementace (modul / UI) | Ověření | Stav / omezení |
|---|---|---|---|
| **1. Očekávaný výsledek a kvantifikace odchylky** | `features/episodes.py` (ukazatel), `models/peer_median.py` (LOO peer medián), `analysis/residuals.py`, `analysis/detectors.py`; UI Pacienti – sloupce Pozorováno/Očekávání/Rozdíl/Míra, stav „nelze posoudit“ s důvodem | `test_baseline.py`, `test_features.py`, `test_analysis.py`, `scripts/check_real_data.py` (LOO na skutečných datech) | **Hotovo.** 107/157 skutečných pacientů hodnotitelných; zbytek s explicitním důvodem |
| **2. Vysvětlení jednotlivce na úrovni znaků** | `analysis/explanations.py` (A očekávání, B označení + kontrafaktuál, C rozdíly charakteristik vs. peerům); UI detail pacienta „Proč je neobvyklý“, panel Vyšetřovaný výběr | AppTest (`test_full_doctor_flow` – vrstva A zobrazena), ruční kontrola snímků (syntetika) | **Hotovo.** Vrstva C je deskriptivní (hypotézy), ne kauzální rozklad |
| **3. Vysvětlení skupiny (shlukování uvnitř outlierů)** | `analysis/clustering.py`, `explanations.describe_groups`; UI Analýza odchylek → Skupinové vzorce, `group_summary.csv` | `test_clustering_uses_only_outliers_and_does_not_invent_groups`, `check_real_data.py` | **Hotovo.** Na skutečných datech při výchozím prahu jen 3 outlieři → aplikace korektně hlásí „příliš málo případů“; skupiny vzniknou při nižším prahu nebo 2 ukazatelích |
| **4. Dashboard, human-in-the-loop, CSV export** | `ui/patients.py`, `ui/deviations.py`, `ui/components.review_panel`, `storage/csv_store.py`, `storage/exports.py` | `test_storage.py` (persistence, kontext, export pořadí/konfigurace), AppTest (uložení posouzení, změna prahu/ukazatelů, návrat), spuštění serveru (`/_stcore/health` = ok) | **Hotovo.** Jeden proces / jeden zapisující uživatel |

## Hodnoticí kritéria
| Kritérium | Jak řešeno | Stav |
|---|---|---|
| Klinická relevance, ne artefakty | ukazatel jen z dokončených pobytů s dg. nádoru; validace dat; příznaky kvality v detailu; posouzení „Podezření na datový problém“ + vyřazení z výpočtu | hotovo; relevance čeká na mentora |
| Interpretovatelnost | české klinické popisky, texty A/B/C z čísel výpočtu, graf reference, „Jak číst tento přehled“ | hotovo |
| Human-in-the-loop | posouzení + komentář + historie; vyřazení pacienta → nová globální konfigurace; lokální reference, práh, ukazatele, škála; uložené pohledy | hotovo (žádné „učení AI“ z kliknutí) |
| Nejistota | stavy reference (ok/omezená/nelze), opora pobytů, pásma, citlivost prahu, kvartily reference | hotovo |
| UX | dvě stránky, výchozí naplněný pohled, filtry, proklik ID → detail → analýza a zpět | hotovo; gesta v grafech jen ručně ověřena |

## Další požadavky zadání
| Požadavek | Implementace | Ověření | Stav |
|---|---|---|---|
| Validovaný import z adresáře i uploadu, blokující vs. neblokující | `data/validation.py`, `data/dataset.py`, sidebar | `test_blocking_errors_reject_dataset` | hotovo |
| Content fingerprint, oddělení anotací | `data/io.fingerprint_files`, `CsvStore` | `test_fingerprint_depends_on_content`, `test_review_from_other_dataset_or_context_is_not_current` | hotovo |
| Bez syntetického režimu – jen skutečná data | `ui/state.py`, obrazovka „Chybí data“ | AppTest `test_without_data_shows_error_not_synthetic` | hotovo |
| Nová popisná vlastnost bez přepisu UI | `features/extra.py`, sidebar, detail, filtry, popis skupin | `test_extra.py` | hotovo |
| Ochrana proti vzorcům v exportu | `exports.excel_safe` | `test_excel_safe_only_touches_text_columns` | hotovo |
| Tři množiny pacientů oddělené | `ui/state.py`, `ui/deviations.py` | `test_local_analysis_never_changes_global_baseline` | hotovo |
| Druhý baseline (P1): Ridge nad log1p s LOO a rozkladem stejného fitu | `models/regression.py`, volba v postranním panelu, tabulka rozkladu v detailu | `test_regression.py`, AppTest `test_global_recompute_creates_new_context` | **hotovo** |
| Isolation Forest, bootstrap, PCA (P1) | – | – | **neimplementováno** (viz TASKS) |
