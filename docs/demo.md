# Demo scénář (3–5 min)

Aplikace pracuje jen se skutečnými daty z `data/` (syntetický režim byl odstraněn). Skutečná data ukazujte jen
týmu a mentorům lokálně; nedělejte z nich snímky obrazovky do veřejných slajdů.

```powershell
python -m uv run streamlit run app.py --server.address 127.0.0.1
```

## Průchod
1. **Případ (Pacienti, 45 s).** Přečíst dvě věty nahoře (co sledujeme, s kým porovnáváme), ukázat počty
   *Lze porovnat* a *Neobvyklé případy* a seřazený seznam se sloupcem *Spolehlivost*.
2. **Vysvětlení (60 s).** Kliknout na řádek. Souhrnná karta: kratší/delší než očekávání, tři hodnoty, počet
   pobytů a srovnávaných pacientů, stav prahu. Karta „Pacient a srovnávací skupina“ (graf, co nebylo zohledněno),
   rozbalit „Jak vzniklo očekávání a označení“ jen pro zájemce. „Co ověřit v kontextu“ a „Podklady a dostupnost“.
   Záložka Epizody péče (pobyty ve výpočtu oranžově).
3. **Skupina (60 s).** „Prozkoumat v analýze odchylek“ → pacient zvýrazněn. Záložka *Skupinové vzorce*: skupina
   s delšími pobyty a více D70 epizodami vs. referencí, varování o skladbě diagnóz.
4. **Feedback (45 s).** „Posoudit případ“ → v okně zvolit „Klinicky zajímavé“, komentář, uložit → stav se změní a zůstane
   po obnovení stránky. Ukázat „Navrhnout vyřazení z výpočtu“ (projeví se až po potvrzení přepočtu v okně
   *Jak počítáme očekávání* v postranním panelu – tam ukázat i volbu metody s nápovědou „?“).
5. **Změna pohledu (30 s).** Přidat ukazatel „Nejdelší pobyt“ → 2D graf + heatmapa; posunout práh; „Použít jako
   referenci“ na filtrovanou skupinu (např. jen leukémie) – globální očekávání se nemění.
6. **Export (15 s).** „Exportovat zobrazený pohled – ZIP“ a otevřít `analysis_results.csv` (posouzení, analýza,
   konfigurace, otisk datasetu).

## Manuální checklist (nepokryto AppTestem)
- [ ] Výběr bodů v grafu (klik, obdélník, laso) se propíše do levého panelu („Vybráno N pacientů z grafu“).
- [ ] „Zobrazit vybrané“ nastaví vyšetřovaný výběr a zvýrazní body; „Zrušit výběr“ ho vymaže.
- [ ] „Použít jako referenci“ změní řádek „Lokální reference“ a standardizaci, ne očekávání v detailu.
- [ ] Klik do libovolné buňky řádku v tabulce Pacienti (bez zaškrtávacího pole) otevře detail téhož ID, i po
      přeřazení sloupců kliknutím na záhlaví; „← Zpět na seznam“ vrátí přehled. Totéž v tabulce podobných pacientů.
- [ ] *Jak počítáme očekávání*: zaškrtnutí jiné volby odškrtne předchozí, „?“ ukáže vysvětlení, „Přepočítat
      očekávání“ okno zavře a změní ID konfigurace v liště stránky; dřívější posouzení se ukáže v historii
      „jiný kontext“. Křížek okno zavře bez změny.
- [ ] Postranní panel neukazuje otisk datasetu ani technické údaje; ikony stránek jsou dobře čitelné.
- [ ] Import `extra_features.csv` → vlastnost v detailu („Nádor a data“), filtru a popisu skupin.
- [ ] Nahrání neplatných CSV ponechá původní dataset a zobrazí zprávu o validaci.
