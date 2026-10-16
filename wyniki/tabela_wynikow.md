### A. Do końca eksperymentu (200 s symulacji, średnia z 3 nodów)

| Strategia | Energia końcowa | Pomiary odebrane | Pomiary wygenerowane | Zmiany trybu | Czas ACTIVE [s] | Czas DEGRADED [s] | Czas SLEEP [s] | Narzut | Czas życia do FAILED [s] | Czas do poziomu 20 [s] | Dostępność |
|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|
| Bez zarządzania (STATUS 2 s) | 0.0 | 151 | 151 | 0 | 75.0 | 0.0 | 0.0 | 21.4 % | 76.0 | 61.0 | 37.5 % |
| Adaptacyjna | 0.0 | 137 | 137 | 2 | 38.0 | 39.5 | 58.0 | 36.6 % | 136.5 | 78.5 | 67.7 % |
| Adaptacyjna + rzadszy STATUS w SLEEP | 0.0 | 143 | 143 | 2 | 38.0 | 39.5 | 78.5 | 31.2 % | 157.0 | 78.5 | 78.0 % |
| Adaptacyjna + priorytet node_1 | 0.0 | 139 | 139 | 2 | 42.7 | 35.7 | 47.8 | 34.8 % | 127.2 | 74.5 | 63.1 % |
| Adaptacyjna, wariant B kosztu SLEEP | 3.7 | 158 | 158 | 2 | 38.0 | 39.5 | 121.5 | 41.0 % | — | 78.5 | 99.5 % |
| Bez zarządzania, STATUS 1 s | 0.0 | 138 | 138 | 0 | 68.5 | 0.0 | 0.0 | 34.3 % | 69.5 | 55.5 | 34.2 % |
| Bez zarządzania, STATUS 4 s | 0.0 | 158 | 158 | 0 | 78.5 | 0.0 | 0.0 | 12.7 % | 79.5 | 64.0 | 39.2 % |

### B. Okno obserwacji 100 s symulacji (ten sam czas dla wszystkich strategii)

| Strategia | Energia końcowa | Pomiary odebrane | Pomiary wygenerowane | Zmiany trybu | Czas ACTIVE [s] | Czas DEGRADED [s] | Czas SLEEP [s] | Narzut | Czas życia do FAILED [s] | Czas do poziomu 20 [s] | Dostępność |
|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|
| Bez zarządzania (STATUS 2 s) | 0.0 | 151 | 151 | 0 | 75.0 | 0.0 | 0.0 | 21.4 % | 76.0 | 61.0 | 75.0 % |
| Adaptacyjna | 12.4 | 124 | 124 | 2 | 38.0 | 39.5 | 21.5 | 32.6 % | — | 78.5 | 99.0 % |
| Adaptacyjna + rzadszy STATUS w SLEEP | 14.0 | 124 | 124 | 2 | 38.0 | 39.5 | 21.5 | 30.7 % | — | 78.5 | 99.0 % |
| Adaptacyjna + priorytet node_1 | 9.2 | 129 | 129 | 2 | 42.7 | 35.7 | 20.6 | 31.7 % | — | 74.5 | 99.0 % |
| Adaptacyjna, wariant B kosztu SLEEP | 16.6 | 124 | 124 | 2 | 38.0 | 39.5 | 21.5 | 32.6 % | — | 78.5 | 99.0 % |
| Bez zarządzania, STATUS 1 s | 0.0 | 138 | 138 | 0 | 68.5 | 0.0 | 0.0 | 34.3 % | 69.5 | 55.5 | 68.5 % |
| Bez zarządzania, STATUS 4 s | 0.0 | 158 | 158 | 0 | 78.5 | 0.0 | 0.0 | 12.7 % | 79.5 | 64.0 | 78.5 % |

### C. Polecenia i zarządzanie (cały eksperyment)

| Strategia | Wysłane polecenia | ACK | ERROR | Skuteczność | Czas reakcji: średnia [ms rzecz.] | mediana [ms rzecz.] | maks [ms rzecz.] | Niespójność config [ms rzecz.] | Pakiety zarządcze | Pakiety DATA |
|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|
| Bez zarządzania (STATUS 2 s) | 0 | 0 | 0 | — | — | — | — | 0.0 | 123 | 453 |
| Adaptacyjna | 12 | 12 | 0 | 100.0 % | 0.56 | 0.54 | 1.10 | 6.8 | 237 | 411 |
| Adaptacyjna + rzadszy STATUS w SLEEP | 15 | 15 | 0 | 100.0 % | 0.98 | 0.98 | 2.02 | 14.7 | 195 | 429 |
| Adaptacyjna + priorytet node_1 | 12 | 12 | 0 | 100.0 % | 0.47 | 0.36 | 1.24 | 5.4 | 223 | 417 |
| Adaptacyjna, wariant B kosztu SLEEP | 12 | 12 | 0 | 100.0 % | 0.64 | 0.61 | 1.22 | 7.9 | 330 | 474 |
| Bez zarządzania, STATUS 1 s | 0 | 0 | 0 | — | — | — | — | 0.0 | 216 | 414 |
| Bez zarządzania, STATUS 4 s | 0 | 0 | 0 | — | — | — | — | 0.0 | 69 | 474 |

### D. Wykrywanie niedostępności (FAILED -> UNREACHABLE)

| Strategia | Node | FAILED w t [s sym.] | UNREACHABLE w t [s sym.] | Cisza przed wykryciem [ms sym.] | FAILED -> UNREACHABLE [s sym.] | Fałszywe UNREACHABLE (node wrócił) |
|---|---|---:|---:|---:|---:|---:|
| Bez zarządzania (STATUS 2 s) | node_1 | 76.0 | 82.1 | 6065 | 6.1 | 0 |
| Bez zarządzania (STATUS 2 s) | node_2 | 76.0 | 82.1 | 6063 | 6.1 | 0 |
| Bez zarządzania (STATUS 2 s) | node_3 | 76.0 | 82.1 | 6064 | 6.1 | 0 |
| Adaptacyjna | node_1 | 136.5 | 142.6 | 6100 | 6.1 | 0 |
| Adaptacyjna | node_2 | 136.5 | 142.6 | 6101 | 6.1 | 0 |
| Adaptacyjna | node_3 | 136.5 | 142.6 | 6108 | 6.1 | 0 |
| Adaptacyjna + rzadszy STATUS w SLEEP | node_1 | 157.0 | 175.0 | 18012 | 18.0 | 0 |
| Adaptacyjna + rzadszy STATUS w SLEEP | node_2 | 157.0 | 175.0 | 18011 | 18.0 | 0 |
| Adaptacyjna + rzadszy STATUS w SLEEP | node_3 | 157.0 | 175.0 | 18021 | 18.0 | 0 |
| Adaptacyjna + priorytet node_1 | node_1 | 108.5 | 114.7 | 6163 | 6.2 | 0 |
| Adaptacyjna + priorytet node_1 | node_2 | 136.5 | 142.6 | 6104 | 6.1 | 0 |
| Adaptacyjna + priorytet node_1 | node_3 | 136.5 | 142.6 | 6103 | 6.1 | 0 |
| Bez zarządzania, STATUS 1 s | node_1 | 69.5 | 75.6 | 6065 | 6.1 | 0 |
| Bez zarządzania, STATUS 1 s | node_2 | 69.5 | 75.6 | 6063 | 6.1 | 0 |
| Bez zarządzania, STATUS 1 s | node_3 | 69.5 | 75.6 | 6064 | 6.1 | 0 |
| Bez zarządzania, STATUS 4 s | node_1 | 79.5 | 91.6 | 12123 | 12.1 | 0 |
| Bez zarządzania, STATUS 4 s | node_2 | 79.5 | 91.6 | 12125 | 12.1 | 0 |
| Bez zarządzania, STATUS 4 s | node_3 | 79.5 | 91.6 | 12124 | 12.1 | 0 |

### E. Per node (cały eksperyment)

| Strategia | Node | Pomiary odebrane | Zmiany trybu | Czas do poziomu 20 [s] | Czas życia do FAILED [s] | Czas ACTIVE [s] | Czas DEGRADED [s] | Czas SLEEP [s] |
|---|---|---:|---:|---:|---:|---:|---:|---:|
| Bez zarządzania (STATUS 2 s) | node_1 | 151 | 0 | 61.0 | 76.0 | 75.0 | 0.0 | 0.0 |
| Bez zarządzania (STATUS 2 s) | node_2 | 151 | 0 | 61.0 | 76.0 | 75.0 | 0.0 | 0.0 |
| Bez zarządzania (STATUS 2 s) | node_3 | 151 | 0 | 61.0 | 76.0 | 75.0 | 0.0 | 0.0 |
| Adaptacyjna | node_1 | 137 | 2 | 78.5 | 136.5 | 38.0 | 39.5 | 58.0 |
| Adaptacyjna | node_2 | 137 | 2 | 78.5 | 136.5 | 38.0 | 39.5 | 58.0 |
| Adaptacyjna | node_3 | 137 | 2 | 78.5 | 136.5 | 38.0 | 39.5 | 58.0 |
| Adaptacyjna + rzadszy STATUS w SLEEP | node_1 | 143 | 2 | 78.5 | 157.0 | 38.0 | 39.5 | 78.5 |
| Adaptacyjna + rzadszy STATUS w SLEEP | node_2 | 143 | 2 | 78.5 | 157.0 | 38.0 | 39.5 | 78.5 |
| Adaptacyjna + rzadszy STATUS w SLEEP | node_3 | 143 | 2 | 78.5 | 157.0 | 38.0 | 39.5 | 78.5 |
| Adaptacyjna + priorytet node_1 | node_1 | 143 | 2 | 66.5 | 108.5 | 52.0 | 28.0 | 27.5 |
| Adaptacyjna + priorytet node_1 | node_2 | 137 | 2 | 78.5 | 136.5 | 38.0 | 39.5 | 58.0 |
| Adaptacyjna + priorytet node_1 | node_3 | 137 | 2 | 78.5 | 136.5 | 38.0 | 39.5 | 58.0 |
| Adaptacyjna, wariant B kosztu SLEEP | node_1 | 158 | 2 | 78.5 | — | 38.0 | 39.5 | 121.5 |
| Adaptacyjna, wariant B kosztu SLEEP | node_2 | 158 | 2 | 78.5 | — | 38.0 | 39.5 | 121.5 |
| Adaptacyjna, wariant B kosztu SLEEP | node_3 | 158 | 2 | 78.5 | — | 38.0 | 39.5 | 121.5 |
| Bez zarządzania, STATUS 1 s | node_1 | 138 | 0 | 55.5 | 69.5 | 68.5 | 0.0 | 0.0 |
| Bez zarządzania, STATUS 1 s | node_2 | 138 | 0 | 55.5 | 69.5 | 68.5 | 0.0 | 0.0 |
| Bez zarządzania, STATUS 1 s | node_3 | 138 | 0 | 55.5 | 69.5 | 68.5 | 0.0 | 0.0 |
| Bez zarządzania, STATUS 4 s | node_1 | 158 | 0 | 64.0 | 79.5 | 78.5 | 0.0 | 0.0 |
| Bez zarządzania, STATUS 4 s | node_2 | 158 | 0 | 64.0 | 79.5 | 78.5 | 0.0 | 0.0 |
| Bez zarządzania, STATUS 4 s | node_3 | 158 | 0 | 64.0 | 79.5 | 78.5 | 0.0 | 0.0 |

### F. Powtórzenia tej samego eksperymentu (min–max z przebiegów)

| Strategia | Przebiegi | Pomiary odebrane (średnia z nodów) | Czas życia do FAILED [s] | Narzut [%] | Skuteczność poleceń [%] | Czas reakcji: średnia [ms rzecz.] |
|---|---:|---|---|---|---|---|
| Bez zarządzania | 3 | 151 | 76.0 | 21.4 | — | — |
| Adaptacyjna | 3 | 137 | 136.5 | 36.6 | 100.0 | 0.54–0.82 |

### T. Przebiegi testowe: polecenia, timeouty, duplikaty

| Przebieg | Wysłane polecenia | ACK | ERROR | Skuteczność (ACK/wysłane) | COMMAND_TIMEOUT | GAVE_UP | Duplikaty zignorowane przez nody | Czas reakcji: średnia / maks [ms rzecz.] |
|---|---:|---:|---:|---:|---:|---:|---:|---|
| test_rdzenia | 4 | 3 | 1 | 75.0 % | 0 | 0 | 2 | 0.4 / 0.5 |
| test_strat | 12 | 8 | 0 | 66.7 % | 29 | 4 | 5 | 227.6 / 322.3 |
