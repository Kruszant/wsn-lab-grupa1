# Laboratorium WSN – Grupa 1: zarządzanie energią i cyklem pracy

Sieć sensoryczna: **3 procesy `node` + 1 `sink-manager`**, komunikacja **UDP na `127.0.0.1`**, komunikaty w JSON.
Sink obserwuje stan nodów (STATUS, ALERT), podejmuje decyzję zarządczą, wysyła potwierdzane polecenia `CONFIG`
(ACK / ERROR, timeout i ponowienie tego samego `command_id`) i rejestruje skutki w dzienniku.
Tylko biblioteka standardowa Pythona; `matplotlib` jest potrzebny wyłącznie do wykresów (`analyze.py`).

## 1. Szybki start

```bash
cd wsn_lab
python3 -m venv .venv && .venv/bin/pip install matplotlib       # raz (tylko do wykresów)

# A) cztery osobne terminale (jak w instrukcji laboratoryjnej) - pokazują tabelę stanu sinka na żywo
.venv/bin/python sink_manager.py --config config/sink_test_rdzenia.json --output-dir wyniki/reczny      # terminal 1
.venv/bin/python node.py --config config/node_1.json --output-dir wyniki/reczny                        # terminal 2
.venv/bin/python node.py --config config/node_2.json --output-dir wyniki/reczny                        # terminal 3
.venv/bin/python node.py --config config/node_3.json --output-dir wyniki/reczny                        # terminal 4

# B) jedno polecenie (uruchamia te same 4 procesy)
.venv/bin/python run_experiment.py --sink config/sink_adaptacyjna.json --out wyniki/adaptacyjna --duration-s 200

# C) analiza (tabela + wykresy) wyłącznie z zapisanych plików
.venv/bin/python analyze.py --runs wyniki/bez_zarzadzania wyniki/adaptacyjna --labels "Bez zarządzania" "Adaptacyjna" --out wyniki

# D) testy (42)
.venv/bin/python -m unittest -v test_wsn
```

**Przyspieszenie symulacji.** Instrukcja pozwala przyspieszyć symulację: `time_scale = 10` oznacza, że 1 s czasu
symulacji trwa 0,1 s rzeczywistej. Wszystkie okresy i progi (500 ms, 2 s, 6 s…) są w **czasie symulacji**; wykresy i
tabele też. Wszystkie procesy muszą mieć ten sam `time_scale` – `run_experiment.py` przekazuje go każdemu z nich.
Czas reakcji na polecenie jest mierzony zegarem rzeczywistym i w tabelach przeliczony na „ms symulacji” (×10); np.
6,9 ms sym. ≈ 0,7 ms rzeczywistej.

## 2. Architektura i porty

```text
NODE 1 (6101) ──DATA/STATUS/ALERT/ACK/ERROR──┐
NODE 2 (6102) ──DATA/STATUS/ALERT/ACK/ERROR──┼──► SINK-MANAGER (6000)  ──► management_log.csv, status_log.csv, data_log.csv
NODE 3 (6103) ──DATA/STATUS/ALERT/ACK/ERROR──┘            │
NODE n  ◄──────────── CONFIG ─────────────────────────────┘   (każdy node na własnym porcie)
```

| Plik | Rola |
|---|---|
| `wsn_common.py` | kontrakt komunikatów, **walidacja CONFIG**, energia w liczbach całkowitych, zegar symulacji |
| `node.py` | node: pomiary (sinusoida + szum), STATUS, ALERT, energia, maszyna stanów, obsługa CONFIG |
| `sink_manager.py` | odbiór, **tabela stanu sinka**, polecenia, timeouty/ponowienia, strategia adaptacyjna, dziennik |
| `run_experiment.py` | uruchamia 4 procesy dla jednego eksperymentu |
| `analyze.py` | metryki, tabele i wykresy z zapisanych plików |
| `test_wsn.py` | 42 testy (jednostkowe + integracyjny z prawdziwymi procesami UDP) |
| `config/node_{1,2,3}.json` | konfiguracje trzech nodów |
| `config/sink_*.json` | konfiguracje sinka: `bez_zarzadzania`, `adaptacyjna`, `adaptacyjna_status`, `adaptacyjna_priorytet`, `test_rdzenia` |
| `wyniki/<przebieg>/` | `management_log.csv`, `status_log.csv`, `data_log.csv`, `state_table.csv`, `run_meta.json`, `<node>_truth.json`, `<node>_energy_trace.csv`, `metrics.json` |
| `wyniki/tabela_wynikow.md`, `wyniki/wykres_*.png` | wyniki zbiorcze |

## 3. Kontrakt komunikatów (dokładnie wg instrukcji)

`DATA`, `STATUS`, `CONFIG`, `ACK`, `ERROR`, `ALERT` mają pola z instrukcji laboratoryjnej, bez dodatkowych.
Polecenia zmieniają `sample_period_ms` (100–5000 ms włącznie), `status_period_ms` (500–20000 ms; zakres wybrany
przez nas, instrukcja go nie podaje) i `operating_state` (tylko `ACTIVE`, `DEGRADED`, `SLEEP` – sink nie może
„ustawić” `FAILED`, `STARTING` ani `STOPPED`). Powody `ERROR`: `VALUE_OUT_OF_RANGE`, `INVALID_VALUE_TYPE`,
`UNKNOWN_PARAMETER`, `INVALID_STATE_VALUE`, `WRONG_DESTINATION`, `STALE_CONFIG_VERSION`, `MALFORMED_COMMAND`,
`NODE_NOT_READY`, `NODE_NOT_OPERATIONAL`.

## 4. Stany i maszyna stanów

```text
STARTING ──(startup_ms)──► ACTIVE ◄──► DEGRADED ◄──► SLEEP        (zmiany tylko poleceniem sinka)
   dowolny stan pracy ──(bateria = 0)──► FAILED  (ostatni STATUS "FAILED", potem cisza)
   dowolny stan pracy ──(koniec eksperymentu)──► STOPPED
```

Sink przechowuje dwa **różne** stany: `reported_state` (to, co zgłosił node) i `observed_state` (wniosek sinka).
`UNREACHABLE` jest wyłącznie stanem **obserwowanym** (brak STATUS dłużej niż `max(6 s, 3 × status_period)`) i nie
nadpisuje `reported_state`. Node w stanie `FAILED` zgłasza `FAILED`, a sink po 6 s ciszy widzi go jako
`UNREACHABLE` – w tabeli D widać oba momenty. `STOPPED` jest zapowiedzianym końcem pracy, więc nie jest niedostępnością.

## 5. Mechanizmy wspólne – jak zrealizowane

| Wymaganie | Realizacja |
|---|---|
| STATUS co 2 s | `status_period_ms` w konfiguracji noda; sink może go zmienić poleceniem |
| UNREACHABLE po 6 s | `tick()` w sink_managerze, timeout rośnie razem z okresem STATUS (unika fałszywych alarmów) |
| Polecenia sinka | `CONFIG` z `parameter` ∈ {sample_period_ms, status_period_ms, operating_state} |
| Walidacja → ACK/ERROR | `validate_config()` (czysta funkcja) **przed** jakąkolwiek zmianą |
| Unikatowy `command_id` | `cmd_001`, `cmd_002`… (globalny licznik sinka) |
| Duplikat nie wykonuje się ponownie | node pamięta odpowiedź na każdy `command_id` i odsyła ją bez ponownego wykonania |
| `config_version` | startuje od 1; rośnie dopiero po poprawnym wykonaniu; niesie ją każdy `DATA`, `STATUS` i `ACK` |
| Timeout polecenia | `command_timeout_ms` = 1000 ms sym., do 3 ponowień **tego samego** `command_id`, potem `COMMAND_TIMEOUT … GAVE_UP` |
| Tabela stanu | pola `observed_state`, `reported_state`, `last_status_ns`, `battery_level`, `sample_period_ms`, `expected_/reported_config_version`, `pending_command_id`; plik `state_table.csv` |

Tabela jest aktualizowana **wyłącznie** po komunikatach UDP. Wysłanie `CONFIG` zmienia tylko
`expected_config_version` (zamiar sinka); `sample_period_ms` i `reported_state` zmieniają się dopiero po ACK/STATUS.

### Dziennik `management_log.csv`

Kolumny dokładnie wg instrukcji. Zdarzenia: `STATUS_RECEIVED`, `ALERT_RECEIVED`, `NODE_UNREACHABLE`, `COMMAND_SENT`,
`ACK_RECEIVED`, `ERROR_RECEIVED`, `COMMAND_TIMEOUT`, `CONFIG_MISMATCH`, `CONFIG_RESTORED` oraz pomocnicze:
`NODE_REACHABLE`, `STRATEGY_DECISION` (decyzja zarządcza wraz z obserwowanym poziomem baterii),
`RESTORE_SCHEDULED`, `MISMATCH_OPEN_AT_END`. Kolumna `details` zawiera m.in. `response_ms=`, `duplicate_ack`,
`duplicate_error`, `cause=…`, `duration_ms=…`.

`CONFIG_MISMATCH` otwiera okres, w którym `expected_config_version != reported_config_version` (przyczyna:
`command_in_flight` albo `unexplained_status_report`), a `CONFIG_RESTORED` go zamyka z czasem trwania.
Gdy node zgłasza starszą wersję, a żadne polecenie nie jest w locie, sink odtwarza ostatni zamiar nowym
poleceniem (nowy `command_id`).

## 6. Model energii i założenia interpretacyjne

```text
battery_level początkowo 100.0;  generowanie pomiaru 0.10;  wysłanie DATA 0.50;
wysłanie STATUS 0.25;  odebranie polecenia 0.10;  cykl SLEEP 0.01
```

Koszty są w `config/node_*.json` (sekcja `energy`). Reguły adaptacyjne (w `config/sink_adaptacyjna.json`, decyzje
podejmuje **sink** z obserwowanej baterii): `> 50` ACTIVE/500 ms, `20 < b ≤ 50` DEGRADED/1000 ms, `≤ 20` SLEEP/3000 ms.
Zmiana trybu to dwa polecenia: najpierw `operating_state`, po jego ACK `sample_period_ms`.

Instrukcja jest w kilku miejscach niejednoznaczna; przyjęliśmy (wszystko w konfiguracji lub w kodzie z komentarzem):

1. **„Cykl SLEEP 0.01”** – w stanie SLEEP node dalej mierzy z okresem 3000 ms (tak mówi reguła adaptacyjna),
   a każdy taki cykl kosztuje dodatkowo 0,01 ponad zwykły koszt pomiaru i wysłania.
2. **Odebranie polecenia (0.10)** płaci się za każdy odebrany datagram, także za duplikat (fizycznie został odebrany).
3. **Bateria 0 ⇒ FAILED.** Instrukcja nie mówi, co się dzieje przy 0; bez tego bateria byłaby ujemna.
4. **`sent_packets` w STATUS** = liczba wysłanych pakietów `DATA` (zgodnie z przykładem: `42` w obu komunikatach).
5. **`sequence`** zaczyna się od 1; **`config_version`** od 1.
6. **ALERT `LOW_BATTERY`** wysyłany jest tylko raz, gdy bateria po raz pierwszy osiągnie `≤ 20`.
7. **Energia w liczbach całkowitych** (jednostki 0,001) – na floatach `100 − 500·0,1` nie daje równo `50.0`, a progi
   `> 50` i `≤ 20` są ostre. Test: `test_arytmetyka_calkowita_zamiast_float`.
8. **Czas reakcji** liczymy od **pierwszego** wysłania polecenia do odbioru ACK (ponowienia nie zerują licznika).
9. **Dostępność** = czas, gdy node jest osiągalny **i** raportuje ACTIVE/DEGRADED/SLEEP, / czas eksperymentu.
   Okres rozruchu (STARTING, 1 s) i czas po FAILED/UNREACHABLE nie liczą się jako dostępność.
10. **Narzut zarządzania** = (STATUS + CONFIG + COMMAND + ACK + ERROR + ALERT, z ponowieniami i duplikatami) /
    (to samo + DATA) – wszystkie pakiety widziane przez sink w obu kierunkach.
11. **Zero czasu eksperymentu** sinka to pierwszy odebrany komunikat (a nie start procesu), żeby sink nie kończył
    pracy przed nodami.

## 7. Test wspólnego rdzenia (kroki 1–8 z instrukcji)

Scenariusz `config/sink_test_rdzenia.json` (czasy w s symulacji), przebieg w `wyniki/test_rdzenia/`:

| t | Polecenie sinka | Zdarzenia w `management_log.csv` |
|---|---|---|
| 8 | `sample_period_ms=1000` → node_1 | `COMMAND_SENT cmd_001` → `ACK_RECEIVED APPLIED`, `config_version 1→2` (`CONFIG_MISMATCH` → `CONFIG_RESTORED`, 6 ms sym.) |
| 14 | `sample_period_ms=50` (poza zakresem) | `ERROR_RECEIVED VALUE_OUT_OF_RANGE`, node nadal na wersji 2 (sink cofa `expected` do 2) |
| 20 | **ten sam** `cmd_002` jeszcze raz | `duplicate_test_resend` → `ERROR_RECEIVED … duplicate_error` (węzeł odesłał zapamiętaną odpowiedź) |
| 24 | `sample_period_ms=1000` (poprawne) | `cmd_003` → `ACK APPLIED`, wersja 3 |
| 28 | **ten sam** `cmd_003` jeszcze raz | `ACK_RECEIVED … duplicate_ack`; node: `duplicates_ignored = 2`, `commands_applied = 2`, `config_version = 3` (nie 4) |

Potwierdzone w `node_1_truth.json` i automatycznie w `test_wsn.TestIntegracja.test_rdzen_ack_error_duplikat`.
Tabela stanu sinka po teście (`state_table.csv`) zgadza się z raportami nodów: node_1 `reported_config_version = 3`,
node_2 i node_3 – 1; sink odebrał tyle `DATA`, ile node wysłał (UDP na localhost bez strat).

## 8. Wyniki wariantu Grupy 1

Eksperymenty: 200 s symulacji, `time_scale = 10`, trzy nody z identyczną konfiguracją; wszystkie liczby pochodzą z
`wyniki/*/` przez `analyze.py` (pełna tabela: `wyniki/tabela_wynikow.md`). Strategie:
**Bez zarządzania** (stale ACTIVE, 500 ms), **Adaptacyjna** (progi 50/20), oraz dwa dodatki do pytań 3–5:
**Adaptacyjna + rzadszy STATUS w SLEEP** (`status_period_ms = 6000` po wejściu w SLEEP) i
**Adaptacyjna + priorytet node_1** (progi 30/10 tylko dla node_1).

### Tabela wyników (wymagana w instrukcji)

Okno 100 s symulacji – ten sam czas obserwacji dla obu strategii (średnia z 3 nodów):

| Strategia | Energia końcowa | Pomiary odebrane | Pomiary wygenerowane | Zmiany trybu | Czas ACTIVE [s] | Czas DEGRADED [s] | Czas SLEEP [s] | Narzut | Czas życia do FAILED [s] | Czas do poziomu 20 [s] | Dostępność |
|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|
| Bez zarządzania | 0.0 | 151 | 151 | 0 | 75.0 | 0.0 | 0.0 | 21.4 % | 76.0 | 61.0 | 75.0 % |
| Adaptacyjna | 12.6 | 124 | 124 | 2 | 38.0 | 39.5 | 21.5 | 32.6 % | — | 78.5 | 99.0 % |
| Adaptacyjna + rzadszy STATUS w SLEEP | 14.3 | 124 | 124 | 2 | 38.0 | 39.5 | 21.5 | 30.7 % | — | 78.5 | 99.0 % |
| Adaptacyjna + priorytet node_1 | 9.4 | 129 | 129 | 2 | 43.4 | 34.3 | 21.3 | 31.7 % | — | 74.2 | 98.7 % |

Do końca eksperymentu (200 s; w obu strategiach baterie są wtedy wyczerpane, więc „energia końcowa” = 0 i
porównanie opiera się na czasie życia i liczbie pomiarów):

| Strategia | Energia końcowa | Pomiary odebrane | Pomiary wygenerowane | Zmiany trybu | Czas ACTIVE [s] | Czas DEGRADED [s] | Czas SLEEP [s] | Narzut | Czas życia do FAILED [s] | Czas do poziomu 20 [s] | Dostępność |
|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|
| Bez zarządzania | 0.0 | 151 | 151 | 0 | 75.0 | 0.0 | 0.0 | 21.4 % | 76.0 | 61.0 | 37.5 % |
| Adaptacyjna | 0.0 | 137 | 137 | 2 | 38.0 | 39.5 | 58.5 | 36.6 % | 137.0 | 78.5 | 68.0 % |
| Adaptacyjna + rzadszy STATUS w SLEEP | 0.0 | 144 | 144 | 2 | 38.0 | 39.5 | 79.0 | 31.4 % | 157.5 | 78.5 | 78.2 % |
| Adaptacyjna + priorytet node_1 | 0.0 | 139 | 139 | 2 | 43.4 | 34.3 | 49.0 | 34.8 % | 127.7 | 74.2 | 63.3 % |

### Wykresy (z `status_log.csv`, czyli z tego, co zaobserwował sink)

1. `battery_level` w funkcji czasu dla obu strategii: `wyniki/wykres_bateria.png`

![bateria](wyniki/wykres_bateria.png)

2. `sample_period_ms` w funkcji czasu dla strategii adaptacyjnej: `wyniki/wykres_okres_probkowania.png`

![okres próbkowania](wyniki/wykres_okres_probkowania.png)

### Polecenia, narzut i wykrywanie niedostępności

| Strategia | Wysłane polecenia | ACK | ERROR | Skuteczność | Czas reakcji: średnia [ms sym.] | mediana [ms sym.] | maks [ms sym.] | Niespójność config [ms sym.] | Pakiety zarządcze | Pakiety DATA |
|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|
| Bez zarządzania | 0 | 0 | 0 | — | — | — | — | 0.0 | 123 | 453 |
| Adaptacyjna | 12 | 12 | 0 | 100.0 % | 6.9 | 6.2 | 12.3 | 83.1 | 237 | 411 |
| Adaptacyjna + rzadszy STATUS w SLEEP | 15 | 15 | 0 | 100.0 % | 4.8 | 3.6 | 9.9 | 71.6 | 198 | 432 |
| Adaptacyjna + priorytet node_1 | 12 | 12 | 0 | 100.0 % | 4.2 | 3.8 | 8.2 | 49.9 | 223 | 417 |

| Strategia | Node | FAILED w t [s] | UNREACHABLE w t [s] | Cisza przed wykryciem [ms] | FAILED -> UNREACHABLE [s] |
|---|---|---:|---:|---:|---:|
| Bez zarządzania | node_1 | 76.1 | 82.1 | 6069 | 6.1 |
| Bez zarządzania | node_2 | 76.0 | 82.1 | 6090 | 6.1 |
| Bez zarządzania | node_3 | 76.0 | 82.1 | 6076 | 6.1 |
| Adaptacyjna | node_1 | 137.0 | 143.1 | 6083 | 6.1 |
| Adaptacyjna | node_2 | 137.0 | 143.1 | 6085 | 6.1 |
| Adaptacyjna | node_3 | 137.0 | 143.1 | 6082 | 6.1 |
| Adaptacyjna + rzadszy STATUS w SLEEP | node_1 | 157.5 | 175.5 | 18013 | 18.0 |
| Adaptacyjna + rzadszy STATUS w SLEEP | node_2 | 157.5 | 175.5 | 18007 | 18.0 |
| Adaptacyjna + rzadszy STATUS w SLEEP | node_3 | 157.5 | 175.5 | 18012 | 18.0 |
| Adaptacyjna + priorytet node_1 | node_1 | 109.0 | 115.5 | 6107 | 6.4 |
| Adaptacyjna + priorytet node_1 | node_2 | 137.0 | 143.1 | 6027 | 6.0 |
| Adaptacyjna + priorytet node_1 | node_3 | 137.0 | 143.7 | 6075 | 6.7 |

### Obserwacje

- **Zużycie energii.** Bez zarządzania bateria spada o ok. 1,33 jednostki na sekundę (pomiar co 500 ms kosztuje 0,6,
  STATUS co 2 s dokłada 0,125 na sekundę) i node przechodzi w FAILED po ok. 76 s. Strategia adaptacyjna zwalnia
  zużycie po przekroczeniu progów i przedłuża pracę do ok. 137 s.
- **Decyzja na podstawie obserwacji.** Pierwsza decyzja zapada przy poziomie baterii ok. 48,8, a nie 50,0, bo sink
  widzi tylko co 2 s (STATUS); drugą (SLEEP) wywołuje `ALERT LOW_BATTERY` (poziom 19,85). To opóźnienie decyzji
  wynika z okresu raportowania i jest cechą zarządzania opartego na obserwacji.
- **Skuteczność poleceń** wyniosła 100 %, czas reakcji ok. 7 ms sym. (≈ 0,7 ms rzeczywistej), łączny czas niespójności
  konfiguracji to suma tych samych kilku milisekund na polecenie.
- **Wykrywanie niedostępności:** FAILED → UNREACHABLE trwa 6,1 s (timeout 6 s); po wydłużeniu okresu STATUS w SLEEP
  do 6 s timeout rośnie do 18 s, więc awaria jest wykrywana trzy razy później – to cena oszczędzania energii na STATUS.

## 9. Odpowiedzi na pytania

**1. Jak strategia wpłynęła na zużycie energii?**
Zużycie spadło po przekroczeniu progów: w oknie 100 s strategia adaptacyjna ma jeszcze 12,6 energii, a brak zarządzania
0 (node pada w ok. 76 s). Czas życia wzrósł z 76 s do 137 s (+80 %), a czas do poziomu krytycznego 20 z 61 s do 78,5 s.

**2. Jaki był koszt oszczędzania energii w liczbie pomiarów?**
W oknie 100 s: 124 pomiary zamiast 151 (−18 %). Do całkowitego wyczerpania baterii: 137 zamiast 151 (−9 %). Strategia
adaptacyjna daje więc dłuższą dostępność, ale **mniej** pomiarów łącznie: energia na jeden pomiar jest wyższa, bo
STATUS (0,25 co 2 s) i koszt cyklu SLEEP są stałe, a pomiary rzadsze. Kompromis „czas pracy kontra liczba pomiarów”
jest tu wyraźny; strategia opłaca się, gdy ważniejsza jest ciągłość obserwacji niż gęstość próbek.

**3. Czy częstszy STATUS skraca czas pracy?**
Tak. STATUS zużywa 0,125 energii na sekundę, czyli ok. 9 % zużycia przy 500 ms, ale ok. 38 % w SLEEP (0,125 z ok. 0,33).
Test: STATUS co 6 s po wejściu w SLEEP wydłużył życie ze 137 s do 157,5 s (+15 %) i dał 144 zamiast 137 pomiarów, kosztem
18 s zamiast 6 s na wykrycie awarii.

**4. Czy SLEEP powinien całkowicie wyłączać status?**
Nie całkowicie. Bez STATUS sink nie odróżni uśpionego noda od uszkodzonego (zobaczy tylko `UNREACHABLE`), nie zobaczy
poziomu baterii ani wersji konfiguracji i nie zweryfikuje, że polecenie `WAKE`/zmiana trybu zadziałała. Rozsądny
kompromis: rzadki STATUS w SLEEP (jak w naszym wariancie) razem z dostosowaniem timeoutu sinka (`3 × status_period`),
żeby sam sink nie wywołał fałszywego alarmu. Pełne wyłączenie wymagałoby innego wykrywania niedostępności.

**5. Jak chronić dane z węzła o wysokim priorytecie?**
Dla node_1 ustawiliśmy niższe progi (DEGRADED poniżej 30, SLEEP poniżej 10 zamiast 50 i 20). Efekt: node_1 dostarczył
143 pomiary zamiast 137 (+4 %), ale żył krócej (109 s zamiast 137 s). Ochrona danych priorytetowych ma więc swoją cenę
w czasie życia. Inne sposoby: nie przełączać go w SLEEP (tylko DEGRADED), zarezerwować rezerwę energii, wcześniej
ograniczać nody o niskim priorytecie, rzadszy STATUS z priorytetowego noda lub jego pierwszeństwo w kolejce poleceń.
Mechanizm jest w konfiguracji sinka (`strategy.node_overrides`).

## 10. Pułapki (na AI i nie tylko) i jak je rozwiązano

Wniosek z instrukcji: kod pisany z pomocą AI łatwo „działa”, ale myli zegary, liczy duplikaty i zmienia stan przed
walidacją. Każdy punkt ma test; dodatkowo sprawdzono testy **mutacyjnie** (celowo psuliśmy kod i sprawdzaliśmy, czy
testy to wychwycą – wszystkie 6 mutacji zostało wykrytych).

| Pułapka | Jak rozwiązano | Test |
|---|---|---|
| `FAILED` ≠ `UNREACHABLE` | dwie osobne kolumny tabeli: `reported_state` i `observed_state`; UNREACHABLE nie nadpisuje stanu raportowanego | `test_failed_raportowany_a_potem_unreachable`, `test_niedostepnosc_po_6_s_to_nie_failed` |
| Duplikat polecenia wykonany drugi raz | node pamięta odpowiedź na `command_id`, duplikat tylko ją powtarza (a energia za odbiór jest nadal liczona) | `test_duplikat_nie_jest_wykonany_ponownie`, test integracyjny |
| Aktualizacja konfiguracji **przed** walidacją | `validate_config()` przed `_apply()`; ERROR zostawia stan, wersję i okres bez zmian | `test_niepoprawne_polecenie_error_bez_zmiany` |
| `True`/`False` jako liczba (`isinstance(True, int)`) | `is_int()` odrzuca `bool`; odrzucamy też `500.0` i `"500"` | `test_bool_nie_jest_poprawna_liczba`, `test_zly_typ` |
| Granice zakresu (100 i 5000 włącznie) | testy 99/100/5000/5001 | `test_granice_zakresu` |
| Progi baterii 50 i 20 na floatach | energia w liczbach całkowitych, progi `>50`, `≤20` | `test_progi_wlacznie_i_wylacznie`, `test_adaptacyjna_dokladnie_na_progach` |
| Tabela „zgaduje” skutek polecenia | po wysłaniu CONFIG zmienia się tylko `expected_config_version`; okres i stan – dopiero po ACK/STATUS | `test_tabela_aktualizowana_tylko_komunikatami` |
| Mieszanie zegarów | jeden zegar (`perf_counter_ns`), czas reakcji liczony z zegara sinka, nie z `timestamp_ns` noda | `test_czas_reakcji_z_zegara_sinka_nie_z_pola_noda` |
| ERROR zostawia błędną wersję oczekiwaną | po ERROR `expected_config_version` wraca do wersji noda, bez pętli ponowień | `test_error_cofa_wersje_oczekiwana` |
| Stary / zdublowany STATUS i DATA | `status_sequence` i `sequence`: stare ignorowane, duplikat DATA nie jest nową próbką | `test_stary_i_zdublowany_status_ignorowany`, `test_duplikat_data_to_nie_nowa_probka` |
| Fałszywy UNREACHABLE po wydłużeniu okresu STATUS | timeout = `max(6 s, 3 × status_period)` | `test_timeout_dostosowany_do_okresu_status` |
| ALERT wysyłany wielokrotnie | flaga „już wysłany”, jeden alarm przy pierwszym ≤ 20 | `test_alert_low_battery_tylko_raz` |
| Martwy node odpowiada | po FAILED node milczy, także na polecenia | `test_wyczerpanie_to_failed_i_cisza` |
| Wiele poleceń naraz do jednego noda | max 1 polecenie w locie; kolejne czekają w kolejce | `test_strategia_adaptacyjna_na_podstawie_obserwacji` |
| Śmieciowe datagramy | `decode()` nie rzuca wyjątku; uszkodzone komunikaty są liczone i ignorowane | `test_decode_nie_wywala_sie_na_smieciach`, `test_uszkodzone_i_nieznane_komunikaty` |
| Sink kończy przed nodami (rozjazd startu) | zero czasu eksperymentu = pierwszy komunikat + `grace_s` | wykryte na przebiegu: pierwotnie 66 z 78 pomiarów |
| Wyniki „z pamięci”, a nie z danych | `analyze.py` czyta tylko pliki CSV/JSON | – |

## 11. Ograniczenia

- UDP na localhost praktycznie nie gubi pakietów, więc ścieżka ponowień jest przetestowana jednostkowo (fałszywy
  zegar), a w przebiegach rzeczywistych skuteczność poleceń to 100 %. Node ma haki testowe (`test_hooks.
  drop_command_prob`, `drop_reply_prob`) do symulacji strat, domyślnie wyłączone.
- Energia jest abstrakcyjna; listening radia nie ma kosztu, więc SLEEP „nic nie kosztuje” poza cyklem 0,01.
- Wszystkie trzy nody mają ten sam model, więc ich wyniki są niemal identyczne; różnią się tylko ziarnem szumu.
- Przy bardzo dużym `time_scale` (> ~20) opóźnienia systemowe zaczynają być porównywalne z okresami symulacji.

## 12. Checklista z instrukcji

- [x] Uruchomiono trzy nody i sink-manager (`run_experiment.py` lub 4 terminale).
- [x] Sink odbiera `DATA` i `STATUS` (`data_log.csv`, `status_log.csv`).
- [x] Każdy node odbiera polecenia na osobnym porcie (6101–6103).
- [x] Poprawne polecenie kończy się `ACK`; niepoprawne – `ERROR`.
- [x] Duplikat polecenia nie jest wykonywany ponownie.
- [x] Kontrola `config_version` (node, sink, okresy niespójności).
- [x] Zmierzono czas reakcji i skuteczność poleceń; obliczono narzut zarządzania.
- [x] Zapisano `management_log.csv` (w każdym folderze `wyniki/<przebieg>/`).
- [x] Wykonano pełny wariant grupowy (dwie wymagane strategie + dwa dodatki).
- [x] Wykresy powstały z zapisanych danych.
