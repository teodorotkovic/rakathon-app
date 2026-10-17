# Rakathon 2026 – Když realita překoná prognózu

Lokální Streamlit aplikace pro **interpretovatelnou analýzu pacientů dětské onkologie FN Brno s neočekávaným
průběhem zaznamenané péče**. Pro každého pacienta spočítá referenční očekávání z podobných pacientů,
kvantifikuje odchylku, vysvětlí ji, najde opakující se vzorce mezi outliery a umožní lékaři případy posoudit,
okomentovat a exportovat.

> Výzkumný hackathonový prototyp – **nejde o ověřené klinické skóre ani o doporučení léčby**. Nízká zaznamenaná
> zátěž péče neznamená automaticky lepší zdravotní výsledek.

## Dvě obrazovky
- **Pacienti** – nahoře dvě věty „co sledujeme / s kým porovnáváme“, počty *Lze porovnat* a *Neobvyklé případy*,
  filtry a tabulka seřazená podle míry odchylky (neporovnatelní na konci s důvodem, nikdy skrytí; sloupec
  *Spolehlivost*). Kliknutím na řádek se otevře detail: s čím ho porovnáváme, co vyvolává označení, čím se liší,
  časová osa epizod, laboratoře, podobní pacienti, posouzení lékařem, přechod do analýzy. Vysvětlivky jsou dole.
- **Analýza odchylek** – volba ukazatelů/škály/prahu, oddělené role „zobrazit vybrané“ × „použít jako referenci“,
  rozložení odchylek s výběrem bodů, seřazené neobvyklé případy, **skupiny uvnitř outlierů** s popisem vůči
  referenci, kontext charakteristik, uložení/načtení pohledu a export.

**Postranní panel** je záměrně jednoduchý: přepínání stránek, počty pacientů/epizod/laboratoří a tlačítka, která
otevírají velká okna – *Data a import*, *Jak počítáme očekávání* (srozumitelná volba metody a pobytů, každá volba
s nápovědou „?“), *Doplňkové vlastnosti* a jen při potřebě *Upozornění k datům* (důležitá omezení dat prostými
větami; podrobná zpráva o validaci je v exportu `data_quality.csv`).

## Instalace a spuštění (Windows, PowerShell)
Předpoklad: Python 3.12 a `uv` (`python -m pip install --user uv`; pokud `uv` není v PATH, používejte `python -m uv`).
```powershell
python -m uv sync --locked
python -m uv run streamlit run app.py --server.address 127.0.0.1
```
Aplikace běží na http://127.0.0.1:8501. Sběr statistik Streamlitu je vypnutý (`.streamlit/config.toml`).
Po instalaci závislostí nepotřebuje síť.

## Data
- **Skutečná data** patří do `data/` (`patients.csv`, `episodes.csv`, `labs.csv`, volitelně `datapackage.json`).
  Složka je ignorovaná Gitem. Jinou cestu nastavíte proměnnou `RAKATHON_DATA_DIR`.
- **Nahrání v UI:** postranní panel → *Data a import* → nahrát všechny tři CSV najednou → *Ověřit a aktivovat*.
  Import je jeden validovaný krok; při blokující chybě zůstává aktivní původní dataset.
- Aplikace pracuje **jen se skutečnými daty**. Pokud v `data/` chybí nebo neprojdou validací, zobrazí se
  obrazovka „Chybí data“ s importem; syntetická data se negenerují ani nenačítají.
- **Doplňkové vlastnosti:** postranní panel → *Doplňkové vlastnosti* → `extra_features.csv`
  (`patient_id` + nové sloupce). Jsou jen popisné (detail, filtry, popis skupin), nevstupují do očekávání.

## Ukládání a export
- Posouzení, uložené pohledy a doplňkové vlastnosti se ukládají do `runtime/real/<otisk datasetu>/`
  (CSV/JSON, ignorováno Gitem). Posouzení je svázané s otiskem datasetu a globální konfigurací; při změně
  dat nebo cíle se staré posouzení zobrazí jen jako historie.
- Export (tlačítko na obou stránkách) = ZIP s `patient_results.csv`, `analysis_results.csv`, `reviews.csv`,
  `analysis_config.csv`, `group_summary.csv`, `data_quality.csv` a `metadata.json` – přesně zobrazení pacienti
  ve stejném pořadí, s konfigurací, verzemi a otiskem datasetu.
- **Po hackathonu smažte** `data/`, `runtime/` a stažené exporty. Aplikace nic nemaže automaticky.

## Testy a kontroly
```powershell
python -m uv run pytest                                  # 41 testů vč. AppTest průchodů UI
python -m uv run ruff check . ; python -m uv run ruff format --check .
python -m uv run python scripts/check_real_data.py       # strukturální kontrola na skutečných datech (bez výpisu pacientů)
python -m uv run python scripts/profile_data.py          # profil dat do runtime/profile/
```

## Známé limity (výběr)
- Hlavní ukazatel zahrnuje jen dokončené hospitalizace s hlavní diagnózou = diagnóza nádoru; komplikace s jiným
  kódem (D70, Z51, infekce) v něm nejsou. Alternativní pravidla výběru jsou v *Jak počítáme očekávání*.
- Den 0 = první záznam v nemocnici, ne diagnóza; úplnost sledování není známa → počty kontaktů nejsou skórované.
- Referenční kohorta je malá; část pacientů (vzácné diagnózy) nelze posoudit, část má jen omezenou referenci.
- Prahy a hranice reference jsou technické heuristiky, ne klinicky validované hodnoty.
- Jeden proces, jeden zapisující uživatel (viz `docs/decisions/0004-csv-persistence.md`).

## Dokumentace
`AGENTS.md` (pro další vývoj) · `docs/product.md` · `docs/architecture.md` · `docs/data-dictionary.md` ·
`docs/methodology.md` · `docs/requirements-matrix.md` · `docs/demo.md` · `docs/mentor-questions.md` ·
`docs/STATUS.md` · `docs/TASKS.md` · `docs/decisions/`
