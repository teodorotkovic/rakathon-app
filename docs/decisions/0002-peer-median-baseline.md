# 0002 – Peer medián s leave-one-patient-out jako první baseline

**Datum:** 2026-10-16 · **Stav:** přijato

**Rozhodnutí:** `PeerMedianBaseline` s hierarchií (dx+věk+pohlaví → dx+věk → dx → skupina+věk → skupina),
hranicemi 8 (plná) / 4 (omezená) jiných pacientů a očekáváním = medián pacientských hodnot reference.

**Důvody:** lékař přesně vidí, s kým je pacient srovnáván; žádné parametry k fitování; LOO je triviálně správné;
jeden hlas na pacienta. Simulace na skutečných četnostech: 91 plných, 16 omezených, 24 bez reference mezi pacienty
s výsledkem. Regrese (Ridge) je až P1 a musí používat OOF/LOO.

**Důsledky:** vzácné diagnózy se nehodnotí (žádné svévolné slučování); věk/pohlaví nejsou u většiny pacientů
zohledněny (uvedeno ve vysvětlení A); Cox ani vlastní bodové skóre se nepoužívají.
