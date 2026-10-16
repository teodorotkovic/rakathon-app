# Architektura

## Vrstvy a závislosti
```
app.py ─┬─ ui/sidebar.py ──┐
        └─ views/*.py → ui/patients.py, ui/deviations.py
                               │  (ui/state.py: session_state + st.cache_*; ui/components.py; ui/charts.py)
                               ▼
                         pipeline.py  (compute_global, compute_analysis – čisté funkce)
              ┌────────────────┼─────────────────────────┬──────────────────┐
        data/ (io, validation,  features/ (catalog,       models/ (base,     analysis/ (residuals, detectors,
        normalization, dataset, episodes, laboratories,   peer_median)       clustering, similarity,
        demo)                   patient_table, extra)                        explanations)
                               │
                         storage/ (csv_store, exports, base)       domain.py, configuration.py, formatting.py
```
- `data/`, `features/`, `models/`, `analysis/`, `storage/`, `pipeline.py` **neimportují Streamlit**.
- I/O: `data/io.py` (čtení CSV/bytes), `storage/csv_store.py` (runtime), `configuration.py` (config/).
- Stránky jsou soubory ve `views/` (kvůli `st.navigation` i `AppTest.switch_page`); logika je v `ui/`.

## Datové kontrakty (`src/rakathon/domain.py`)
| Kontrakt | Obsah |
|---|---|
| `DatasetBundle` | raw tabulky (text), normalizovaní pacienti/epizody/laboratoře, `fingerprint` (SHA-256 obsahu), `source_mode`, `validation`, volitelně `extra` + `extra_meta` |
| `ValidationReport`/`ValidationIssue` | závažnost (blocking/warning/info), tabulka, sloupec, kód, počet, příklady ID |
| `FeatureSpec` | id, popisek, popis, typ, role (`identifier`/`baseline_input`/`outcome`/`descriptor`/`data_quality`), zdroj, jednotka, agregace, význam missing, dostupnost |
| `OutcomeSpec` | ukazatel, popisek dle pravidla výběru epizod, jednotka, statistika, časová politika, hodnotitelnost |
| `BaselineConfig` | metoda, pravidlo epizod, ukazatele, hierarchie, hranice reference, verze+hash diagnostické mapy, vyřazení pacienti s důvody → `config_id` (`B-…`) |
| `BaselineResult` | long tabulka pacient × ukazatel (observed, expected, residual, log_residual, stavy, reference) + metadata běhu |
| `AnalysisConfig` | ukazatele, škála, práh, margin, zahrnutí omezené reference, lokální reference IDs, prahy citlivosti, parametry shlukování → `analysis_id(fp, baseline_id)` (`A-…`) |
| `AnalysisResult` | `scores` (1 řádek/pacient), `dims` (pacient × ukazatel), `calibration`, `clusters`, `group_summary`, `group_cards`, reference |
| `ReviewRecord` | record_id, fingerprint, source_mode, patient_id, baseline_config_id, analysis_id, label, status, comment, reviewer, created_at, supersedes |

Identita: `config_id`/`analysis_id` = SHA-256 kanonického JSON konfigurace + `FEATURE_SCHEMA_VERSION` +
`METHOD_VERSION` (+ otisk datasetu u analýzy). Změna semantiky výpočtu ⇒ zvýšit verzi v `domain.py`.
Metadata běhu nesou verze Pythonu a knihoven (`pipeline.run_environment`).

## Globální vs. lokální stav (tři množiny pacientů)
| Množina | Kde žije | Jak se mění | Co ovlivní |
|---|---|---|---|
| Globální baseline | `st.session_state["baseline_config"]` | jen formulář **Přepočítat očekávání** / načtení pohledu | očekávání, rezidua, `baseline_config_id`, platnost posouzení |
| Lokální reference detektoru | `AnalysisConfig.reference_ids` | **Použít jako referenci** / **Výchozí reference** | jen kalibraci lokálního skóre (`analysis_id`) |
| Vyšetřovaný výběr | `st.session_state["investigated_ids"]` | **Zobrazit vybrané**, výběr v grafu/seznamu, skupina | jen zvýraznění, vysvětlení, kontext |

Stránka Pacienti vždy používá výchozí `AnalysisConfig` z `config/defaults.json`; experimenty v Analýze odchylek
ji nemění. Detail otevřený z analýzy navíc ukáže lokální skóre s názvem pohledu.

## Tok změn a cache
1. Načtení datasetu: bytes → `fingerprint_files` → `prepare_dataset` (cache podle otisku). Neplatný import se
   neaktivuje. Změna datasetu resetuje výběry, reference, čekající vyřazení a konfigurace.
2. `global_results()` = `st.cache_data` klíčovaná `source_mode:fingerprint:hash(extra)` + kanonický JSON
   `BaselineConfig`.
3. `analysis_for(cfg)` = `st.cache_data` klíčovaná datasetem, `baseline_config_id` a JSON `AnalysisConfig`.
4. Posouzení se **necachují** – čtou se z CSV při každém běhu, po zápisu `st.rerun()`.
5. `st.cache_data` vrací kopie (pickle) – mutace se nepřenáší mezi relacemi.

## Úložiště
`storage/csv_store.py`: `runtime/<source_mode>/<fingerprint[:16]>/` obsahuje `dataset.json`, `reviews.csv`
(append-only log), `analysis_views.csv`, `extra_features.csv` + `extra_features_meta.json`. Zápis přes dočasný
soubor a `os.replace`; read-modify-write pod `threading.Lock` na soubor. Rozhraní `storage/base.py` umožní
pozdější SQLite.

## Rozšíření
Viz `AGENTS.md` §10 (vlastnost, výsledek, baseline, detektor).
