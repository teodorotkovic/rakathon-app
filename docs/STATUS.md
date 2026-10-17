# Stav projektu

Aktualizováno: 2026-10-17, větev `main`, soukromý repozitář `teodorotkovic/rakathon-app`.

## Co funguje
- Import skutečných dat z `data/` i nahráním v UI, validace (blokující/neblokující), content fingerprint,
  syntetický režim odstraněn – aplikace pracuje jen se skutečnými daty.
- Pacientská tabulka (1 řádek/pacient), ukazatele `median_los_dx` / `max_los_dx`, tři pravidla výběru pobytů.
- `PeerMedianBaseline` s hierarchií reference a LOO; rezidua v dnech i log škále.
- Robustní lokální detektor (MAD → IQR → nestandardizovatelné), pásma, opora, citlivost prahu, kontrafaktuál.
- Shlukování jen outlierů a popis skupin vůči lokální referenci a referenci se stejnými diagnózami.
- Stránka Pacienti (přehled, filtry, detail s A/B/C, časová osa, laboratoře, podobní, posouzení) a Analýza odchylek
  (ukazatele/škála/práh, role výběru a reference, grafy s výběrem, seřazené případy, skupiny, kontext, pohledy).
- Persistence posouzení s historií a kontextem, navržení vyřazení pacienta z globálního výpočtu, ZIP export.
- Import doplňkových popisných vlastností s validací a opravitelným typem.
- **P1:** volitelná baseline Ridge nad log1p s LOO a rozkladem příspěvků ze stejného fitu (volba
  „Statistický model“); popisná LOO chyba aktivní metody v *Jak počítáme očekávání → Pokročilé*.
- Zjednodušený postranní panel podle zpětné vazby týmu: bez technických údajů (otisk, zpráva o validaci, cesty),
  větší ikony navigace, velká okna (`st.dialog`) *Data a import*, *Jak počítáme očekávání* (zaškrtávací volby
  s nápovědou „?“), *Doplňkové vlastnosti* a jen při potřebě *Upozornění k datům* (prosté věty).
- Zjednodušená stránka Pacienti: místo technické lišty dvě věty „co sledujeme / s kým porovnáváme“, metriky
  *Lze porovnat* a *Neobvyklé případy*, sloupce *Spolehlivost* a *Podobných pacientů*, otevření detailu
  kliknutím do řádku (bez zaškrtávacích polí a bez výběru podle ID), vysvětlivky pod tabulkou.
- Přestavěný detail pacienta (postupné odkrývání): drobečková navigace, souhrnná karta (věta o směru, stav
  „Práh odchylky překročen/nepřekročen“, tři hodnoty, počty pobytů a srovnávaných pacientů), záložka Přehled se
  čtyřmi kartami (srovnávací skupina s grafem a rozbalovacím „Jak vzniklo očekávání a označení“; Co ověřit
  v kontextu; Posouzení lékařem s formulářem v dialogu; Podklady a dostupnost). Skóre, log škála, citlivost
  a technická ID jsou jen v rozbalovacím detailu.
- **Oprava:** „Relativní rozdíl“ v detailu výpočtu byl `expm1(log1p rozdílu)`, tj. poměr (1 + pozorováno) /
  (1 + očekávání) − 1 (např. −57,9 % místo −73,3 % pro 1 vs. 3,75 dne). Nyní (pozorováno − očekávání) /
  očekávání; test `test_relative_difference_is_against_expectation_not_log1p`.
- Terminologie: „pobyt bez zaznamenaného data propuštění“ místo „neuzavřená hospitalizace“.

## Provedené kontroly (2026-10-16/17)
| Kontrola | Výsledek |
|---|---|
| `python -m uv sync` (Python 3.12.6, streamlit 1.66.0, pandas 3.0.6, numpy 2.5.4, plotly 7.1.0, scikit-learn 1.9.1) | OK |
| `python -m uv sync --locked` | OK |
| `python -m uv run pytest` | 42 passed; detail pacienta ověřen AppTestem i snímky (jen testovací syntetická CSV) – (AppTest: jednoduchý přehled, lékařský průchod, globální přepočet přes dialog, jednoduchý panel + upozornění, dialog importu, reset pohledu, obrazovka bez dat; mapování kliku do buňky na pacienta) |
| Vizuální kontrola stránky Pacienti (jen testovací syntetická CSV): přehled bez zaškrtávacích polí, klik do buňky otevře detail téhož pacienta | OK |
| Ridge vs. peer medián na skutečných datech | 107/157 hodnoceno u obou; medián \|rozdílu\| 1,13 vs. 1,25 dne; Ridge ~8 s výpočtu |
| `python -m uv run ruff check .` | All checks passed |
| `python -m uv run python scripts/check_real_data.py` (skutečná data) | 13/13 OK; 107 hodnotitelných, 3 nad prahem |
| Spuštění `streamlit run app.py` + `GET /_stcore/health` | ok (skutečná i syntetická data) |
| AppTest obou stránek na skutečných datech (ad hoc) | bez výjimek |
| Vizuální kontrola headless Chrome (jen syntetika): přehled, detail, časová osa, analýza, skupiny | OK; nalezené vady opraveny (chybějící export bez uložených pohledů, šířka sloupců) |
| Vizuální kontrola nového panelu (jen testovací syntetická CSV): ikony, dialog nastavení, dialog importu, zavření křížkem | OK |

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
