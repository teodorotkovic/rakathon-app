# Demo scénář (3–5 min)

Aplikace pracuje jen se skutečnými daty z `data/` (syntetický režim byl odstraněn). Skutečná data ukazujte jen
týmu a mentorům lokálně; nedělejte z nich snímky obrazovky do veřejných slajdů.

```powershell
python -m uv run streamlit run app.py --server.address 127.0.0.1
```

## Průchod
1. **Případ (Pacienti, 45 s).** Ukázat metriky (hodnoceno / nad prahem /
   omezená opora / nelze posoudit) a seřazený seznam. Rozbalit „Jak číst tento přehled“.
2. **Vysvětlení (60 s).** Kliknout na první řádek. A: „Očekávání 5 dní = medián 19 pacientů se stejnou diagnózou…
   věk a pohlaví nejsou zohledněny“. Graf reference. B: rozdíl, standardizovaná odchylka, citlivost prahu,
   kontrafaktuál. C: čím se liší od srovnávaných (hypotézy). Záložka Časová osa (pobyty ve výpočtu oranžově).
3. **Skupina (60 s).** „Prozkoumat v analýze odchylek“ → pacient zvýrazněn. Záložka *Skupinové vzorce*: skupina
   s delšími pobyty a více D70 epizodami vs. referencí, varování o skladbě diagnóz.
4. **Feedback (45 s).** V panelu posouzení zvolit „Klinicky zajímavé“, komentář, uložit → stav se změní a zůstane
   po obnovení stránky. Ukázat „Navrhnout vyřazení z výpočtu“ (projeví se až po potvrzení přepočtu).
5. **Změna pohledu (30 s).** Přidat ukazatel „Nejdelší pobyt“ → 2D graf + heatmapa; posunout práh; „Použít jako
   referenci“ na filtrovanou skupinu (např. jen leukémie) – globální očekávání se nemění.
6. **Export (15 s).** „Exportovat zobrazený pohled – ZIP“ a otevřít `analysis_results.csv` (posouzení, analýza,
   konfigurace, otisk datasetu).

## Manuální checklist (nepokryto AppTestem)
- [ ] Výběr bodů v grafu (klik, obdélník, laso) se propíše do levého panelu („Vybráno N pacientů z grafu“).
- [ ] „Zobrazit vybrané“ nastaví vyšetřovaný výběr a zvýrazní body; „Zrušit výběr“ ho vymaže.
- [ ] „Použít jako referenci“ změní řádek „Lokální reference“ a standardizaci, ne očekávání v detailu.
- [ ] Klik na řádek v tabulce Pacienti otevře detail téhož ID; „← Zpět na seznam“ vrátí přehled.
- [ ] Přepočet globálního očekávání (jiné pravidlo pobytů) změní ID konfigurace; dřívější posouzení se ukáže
      v historii „jiný kontext“.
- [ ] Import `extra_features.csv` → vlastnost v detailu („Nádor a data“), filtru a popisu skupin.
- [ ] Nahrání neplatných CSV ponechá původní dataset a zobrazí zprávu o validaci.
