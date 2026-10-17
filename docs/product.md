# Produkt

## Kontext
Rakathon 2026 (Brno), výzva dětské onkologie FN Brno „Když realita překoná prognózu“: interpretovatelná
detekce pacientů s neočekávaným průběhem péče. Tým tří lidí; na místě mentoři z nemocnice.

Klíčový poznatek z konzultace s mentorkou: mezi lékaři a IT je komunikační bariéra – lékař často neví, na co se
dat zeptat. Aplikace mu má umožnit **samostatně** procházet neobvyklé případy, měnit pohled a formulovat
hypotézy bez znalosti ML a bez psaní dotazů programátorům.

## Uživatel
Klinik (dětský onkolog) bez datově-analytického vzdělání. Rozhraní je česky, s klinickými názvy
(„S čím pacienta porovnáváme“, „Délka hospitalizací“, „Proč je případ neobvyklý“); algoritmy jsou až v technickém
detailu.

## Hlavní pracovní postup (implementováno)
1. **Pacienti:** seřazený seznam podle míry odchylky hlavního ukazatele vůči očekávání.
2. **Detail:** v čem a vůči komu je pacient neobvyklý (vysvětlení A/B/C), s čísly z výpočtu.
3. **Kontext:** časová osa epizod (body/intervaly/pobyty bez zaznamenaného data propuštění), diagnózy, laboratoře, podobní pacienti.
4. **Analýza odchylek:** stejný pacient v rozložení celé kohorty, změna ukazatelů/prahu/reference.
5. **Skupiny:** shlukování uvnitř outlierů a popis společných charakteristik vůči referenci.
6. **Zpětná vazba:** posouzení + komentář (uloženo), navržení vyřazení chybných dat z výpočtu, uložení pohledu,
   export ZIP/CSV.

## MVP (P0) – stav v `docs/requirements-matrix.md`
Skutečný import a validace · definovaný výsledek · peer baseline s LOO · rezidua · dvě propojené stránky ·
individuální vysvětlení · shlukování outlierů a skupinové popisy · nejistota/dostupnost · uložená zpětná vazba ·
lokální parametry · export · doplňková popisná vlastnost · dokumentace a testy.

## Ne-cíle
Přežití/Cox, predikce léčebného rozhodnutí, klinická validace, vlastní bodové skóre, obecný BI nástroj,
plná ICCC bez ověřené mapy, LLM chat, integrace s nemocnicí, autentizace, produkční nasazení, SQLite, mobilní
aplikace. Žádné odesílání dat do externích služeb.
