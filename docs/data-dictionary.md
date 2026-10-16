# Datový slovník

Zdroj schématu: `data/datapackage.json` (vydání 2026-10-16). Ověřeno na skutečných CSV dne 2026-10-16
(`scripts/check_real_data.py`, `scripts/profile_data.py`). Uvedeny jsou jen agregované počty, žádné jednotlivé
případy. Počty jsou vodítko pro kontrolu, v kódu nejsou zadrátované.

## Ověřené souhrny vydání
| Položka | Hodnota | Poznámka / rozpor s podklady |
|---|---|---|
| pacienti (`patients.csv`) | 157 řádků, 157 pacientů, `tumor_id=1` u všech | multi-tumor logika testována jen synteticky |
| epizody | 17 864; ambulantní 16 128, dokončené hospitalizace 1 707, bez propuštění 29, neplatné 0 | PDF výzvy uvádí 16 157 ambulantních = 16 128 + 29 neuzavřených; rozhoduje explicitní klasifikace |
| laboratoře | 1 624 výsledků u 49 pacientů; max 569 na pacienta; 769 bez `episode_id`; 18 se záporným dnem; 52 kódů testů, každý s jednou jednotkou; 48 bez mezí; 16 přesných duplicit (ponechány) | 0 neshod epizoda ↔ pacient |
| `stage` | `7` u 122, `9` u 9 → použitelné stadium u 26 | význam `7` nepotvrzen |
| morfologie | `/3` 136, `/1` 17, `/0` 2, `/2` 2; `3333/3` u 6 | zadání zmiňuje jen `/1`, `/3`; ostatní kódy chování zobrazeny raw |
| první epizoda | vždy den 0; u 30 pacientů `Z38` (porod) | den 0 ≠ diagnóza |
| historie | 173–7 346 dní (medián 883) | není důkaz úplného sledování |
| časový posun | datapackage: −3..+3 dny; PDF: „0–3 dny“ | rozhoduje datapackage |
| hlavní ukazatel | 131/157 pacientů má ≥ 1 dokončený pobyt s `dx_main = dx_icd10` (762 pobytů; 19 pacientů jen 1 pobyt) | pacienti s D43/D48 mají pobyty často kódované jinou dg. (C71/D43) |

## `patients.csv` (pacient × nádor)
| Pole | Typ v aplikaci | Role | Zacházení |
|---|---|---|---|
| `patient_id` | text | identifier | jen klíč, nikdy prediktor |
| `tumor_id` | text → `tumor_id_num` | identifier | pořadí nádoru; >1 nádor ⇒ pacient vyřazen z baseline (`multi_tumor`) |
| `sex` | kategorie M/F | baseline_input | |
| `age_group` | uspořádaná kategorie | baseline_input | pořadí `0-5 … 18-20` (`age_order`) |
| `dx_icd10` | kategorie | baseline_input | přesný kód vždy zobrazen |
| `dx_group`, `dx_group_label` | odvozené | baseline_input | `config/diagnosis_groups.csv` (`dxmap-v1`), „orientační diagnostická skupina“; nezařazené kódy bez skupiny |
| `topography_icdo3` | text | descriptor (detail) | není MKN-10 |
| `morphology_icdo3` | text | descriptor | `morphology_status`, `morphology_behaviour(_label)`; `3333/3` = neznámá |
| `laterality`, `extent` | text (raw) | descriptor | významy kódů nepotvrzeny |
| `grade` | text | descriptor | `grade_status`: 1–4 diferenciace / 5–6 buněčný typ / 9 neznámo – ne jedna škála |
| `stage` | text | descriptor | `stage_status`: uvedeno / neznámé (9) / kód 7 nepotvrzen / chybí; nepoužívá se v baseline |
| `t,n,m` | text | descriptor | `tnm_clinical_available` |
| `pt,pn,pm,psu` | text | jen detail | patologické TNM není dostupné v čase očekávání; `psu` nepotvrzeno |
| `deceased` | text 0/1 | jen detail | jediné úmrtí; není výsledkem ani vstupem, vynecháno z popisů skupin |

## `episodes.csv`
| Pole | Zacházení |
|---|---|
| `episode_id` | unikátní; prefix musí odpovídat `patient_id` (jinak blokující chyba); `seq` = pořadí |
| `day_start`, `day_end` | celé dny od první epizody; `day_end` prázdné = hospitalizace bez propuštění |
| `episode_class` (odvozené) | `outpatient` (end = start), `inpatient_completed` (end > start), `inpatient_open` (end chybí), `invalid_interval` (end < start; audit, nepoužito) |
| `los_days` (odvozené) | `day_end − day_start` bez +1, jen dokončené hospitalizace; jinak chybí (ne 0) |
| `dx_main` | hlavní dg. epizody (ne nutně nádor); prázdné = nekódováno |

## `labs.csv`
| Pole | Zacházení |
|---|---|
| `test_code` | text s úvodními nulami; názvy testů neověřeny → zobrazen kód · panel · jednotka |
| `episode_id` | vazba platí jen při shodě obou klíčů (`episode_link`: linked / no_episode / unknown_episode / patient_mismatch); výsledek vždy zůstává u pacienta |
| `day` | může být záporný (není chyba) |
| `value`, `ref_low`, `ref_high` | čísla; meze mohou být dospělé; cenzorování (<, >) není označeno |
| `flag` | L/N/H vůči dodaným mezím, ne závažnost |

## Odvozené vlastnosti pacienta (`features/catalog.py`)
| ID | Role | Definice | Missing |
|---|---|---|---|
| `median_los_dx` | outcome | medián `los_days` vybraných pobytů | žádný pobyt ⇒ chybí + důvod |
| `max_los_dx` | outcome | maximum `los_days` vybraných pobytů | dtto |
| `n_stays_included` | descriptor | počet vybraných pobytů | 0 = žádný pobyt |
| `n_inpatient_completed`, `n_inpatient_open`, `n_outpatient`, `n_d70_episodes`, `n_episodes` | descriptor | počty za celou historii (D70 = kód epizody, ne incidence neutropenie) | — |
| `history_span_days` | descriptor | poslední známý den epizody | — |
| `first_episode_birth` | descriptor | E001 = Z38 | — |
| `anchor_day`, `anchor_episode_id` | descriptor | první epizoda s `dx_main = dx_icd10` (proxy) | bez kotvy = prázdné |
| `has_labs`, `n_lab_results`, `lab_share_low/high` | descriptor | agregace na pacienta; podíly jen z výsledků s mezemi | bez laboratoří: počty 0, podíly chybí |
| `n_invalid_intervals`, `n_dx_missing`, `multi_tumor` | data_quality | | |
| doplňkové vlastnosti | descriptor | `extra_features.csv`, typ numeric/categorical zadaný uživatelem | chybějící řádek ⇒ chybí |

Laboratorní souhrny pro skupiny: `lab_test_patient_medians` = medián hodnoty na pacienta × (kód + jednotka);
srovnává se jen stejný test se stejnou jednotkou.
