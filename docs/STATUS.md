# Stav projektu

Aktualizováno: 2026-10-17 (noc), větev `main`, lokální commity M0–M4, nic nepushnuto.

## Co funguje
- Import skutečných dat z `data/` i nahráním v UI, validace (blokující/neblokující), content fingerprint,
  syntetické demo s výrazným označením.
- Pacientská tabulka (1 řádek/pacient), ukazatele `median_los_dx` / `max_los_dx`, tři pravidla výběru pobytů.
- `PeerMedianBaseline` s hierarchií reference a LOO; rezidua v dnech i log škále.
- Robustní lokální detektor (MAD → IQR → nestandardizovatelné), pásma, opora, citlivost prahu, kontrafaktuál.
- Shlukování jen outlierů a popis skupin vůči lokální referenci a referenci se stejnými diagnózami.
- Stránka Pacienti (přehled, filtry, detail s A/B/C, časová osa, laboratoře, podobní, posouzení) a Analýza odchylek
  (ukazatele/škála/práh, role výběru a reference, grafy s výběrem, seřazené případy, skupiny, kontext, pohledy).
- Persistence posouzení s historií a kontextem, navržení vyřazení pacienta z globálního výpočtu, ZIP export.
- Import doplňkových popisných vlastností s validací a opravitelným typem.

## Provedené kontroly (2026-10-16/17)
| Kontrola | Výsledek |
|---|---|
| `python -m uv sync` (Python 3.12.6, streamlit 1.66.0, pandas 3.0.6, numpy 2.5.4, plotly 7.1.0, scikit-learn 1.9.1) | OK |
| `python -m uv run pytest` | 31 passed (včetně 2 AppTest průchodů UI) |
| `python -m uv run ruff check .` | All checks passed |
| `python -m uv run python scripts/check_real_data.py` (skutečná data) | 13/13 OK; 107 hodnotitelných, 3 nad prahem |
| Spuštění `streamlit run app.py` + `GET /_stcore/health` | ok (skutečná i syntetická data) |
| AppTest obou stránek na skutečných datech (ad hoc) | bez výjimek |
| Vizuální kontrola headless Chrome (jen syntetika): přehled, detail, časová osa, analýza, skupiny | OK; nalezené vady opraveny (chybějící export bez uložených pohledů, šířka sloupců) |

Neověřeno automaticky: gesta výběru v Plotly grafech a klik do tabulky v reálném prohlížeči uživatelem
(viz manuální checklist v `docs/demo.md`).

## Výsledky na skutečných datech (souhrn)
Hlavní ukazatel u 131/157; reference ok 102, omezená 16, nelze 39; hodnotitelných 107; při výchozím prahu 2,5
v 1D jen 3 outlieři (skupiny se nevytvoří – korektně hlášeno). Se dvěma ukazateli 5 outlierů → 2 skupiny
+ 1 izolovaný; v 1D při prahu 2,0 7 outlierů → 2 skupiny. Klinickou relevanci je třeba ověřit s mentorem.

## Limity
Viz `README.md` (Známé limity) a `docs/methodology.md` §7. Jeden proces/jeden zapisující uživatel.

## Příští krok
1. Konzultace s mentorem nad otázkami 1, 4, 8 (`docs/mentor-questions.md`) přímo v aplikaci na skutečných datech.
2. Ruční průchod checklistem v `docs/demo.md` v prohlížeči.
3. P1 podle `docs/TASKS.md` jen pokud zbude čas.
