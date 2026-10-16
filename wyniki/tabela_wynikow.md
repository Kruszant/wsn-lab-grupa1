### A. Do końca eksperymentu (200 s symulacji, średnia z 3 nodów)

| Strategia | Energia końcowa | Pomiary odebrane | Pomiary wygenerowane | Zmiany trybu | Czas ACTIVE [s] | Czas DEGRADED [s] | Czas SLEEP [s] | Narzut | Czas życia do FAILED [s] | Czas do poziomu 20 [s] | Dostępność |
|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|
| Bez zarządzania | 0.0 | 151 | 151 | 0 | 75.0 | 0.0 | 0.0 | 21.4 % | 76.0 | 61.0 | 37.5 % |
| Adaptacyjna | 0.0 | 137 | 137 | 2 | 38.0 | 39.5 | 58.5 | 36.6 % | 137.0 | 78.5 | 68.0 % |
| Adaptacyjna + rzadszy STATUS w SLEEP | 0.0 | 144 | 144 | 2 | 38.0 | 39.5 | 79.0 | 31.4 % | 157.5 | 78.5 | 78.2 % |
| Adaptacyjna + priorytet node_1 | 0.0 | 139 | 139 | 2 | 43.4 | 34.3 | 49.0 | 34.8 % | 127.7 | 74.2 | 63.3 % |

### B. Okno obserwacji 100 s symulacji (ten sam czas dla wszystkich strategii)

| Strategia | Energia końcowa | Pomiary odebrane | Pomiary wygenerowane | Zmiany trybu | Czas ACTIVE [s] | Czas DEGRADED [s] | Czas SLEEP [s] | Narzut | Czas życia do FAILED [s] | Czas do poziomu 20 [s] | Dostępność |
|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|
| Bez zarządzania | 0.0 | 151 | 151 | 0 | 75.0 | 0.0 | 0.0 | 21.4 % | 76.0 | 61.0 | 75.0 % |
| Adaptacyjna | 12.6 | 124 | 124 | 2 | 38.0 | 39.5 | 21.5 | 32.6 % | — | 78.5 | 99.0 % |
| Adaptacyjna + rzadszy STATUS w SLEEP | 14.3 | 124 | 124 | 2 | 38.0 | 39.5 | 21.5 | 30.7 % | — | 78.5 | 99.0 % |
| Adaptacyjna + priorytet node_1 | 9.4 | 129 | 129 | 2 | 43.4 | 34.3 | 21.3 | 31.7 % | — | 74.2 | 99.0 % |

### C. Polecenia i zarządzanie (cały eksperyment)

| Strategia | Wysłane polecenia | ACK | ERROR | Skuteczność | Czas reakcji: średnia [ms sym.] | mediana [ms sym.] | maks [ms sym.] | Niespójność config [ms sym.] | Pakiety zarządcze | Pakiety DATA |
|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|
| Bez zarządzania | 0 | 0 | 0 | — | — | — | — | 0.0 | 123 | 453 |
| Adaptacyjna | 12 | 12 | 0 | 100.0 % | 9.4 | 9.4 | 17.0 | 112.6 | 237 | 411 |
| Adaptacyjna + rzadszy STATUS w SLEEP | 15 | 15 | 0 | 100.0 % | 4.0 | 3.7 | 7.5 | 60.5 | 198 | 432 |
| Adaptacyjna + priorytet node_1 | 12 | 12 | 0 | 100.0 % | 6.5 | 6.8 | 12.5 | 77.8 | 223 | 417 |

### D. Wykrywanie niedostępności (FAILED -> UNREACHABLE)

| Strategia | Node | FAILED w t [s] | UNREACHABLE w t [s] | Cisza przed wykryciem [ms] | FAILED -> UNREACHABLE [s] |
|---|---|---:|---:|---:|---:|
| Bez zarządzania | node_1 | 76.0 | 82.1 | 6111 | 6.1 |
| Bez zarządzania | node_2 | 76.0 | 82.1 | 6110 | 6.1 |
| Bez zarządzania | node_3 | 76.0 | 82.1 | 6110 | 6.1 |
| Adaptacyjna | node_1 | 137.0 | 143.1 | 6073 | 6.1 |
| Adaptacyjna | node_2 | 137.0 | 143.1 | 6074 | 6.1 |
| Adaptacyjna | node_3 | 137.0 | 143.1 | 6082 | 6.1 |
| Adaptacyjna + rzadszy STATUS w SLEEP | node_1 | 157.5 | 175.6 | 18103 | 18.1 |
| Adaptacyjna + rzadszy STATUS w SLEEP | node_2 | 157.5 | 175.6 | 18124 | 18.1 |
| Adaptacyjna + rzadszy STATUS w SLEEP | node_3 | 157.5 | 175.6 | 18123 | 18.1 |
| Adaptacyjna + priorytet node_1 | node_1 | 109.0 | 115.1 | 6039 | 6.0 |
| Adaptacyjna + priorytet node_1 | node_2 | 137.0 | 143.1 | 6082 | 6.1 |
| Adaptacyjna + priorytet node_1 | node_3 | 137.0 | 143.1 | 6079 | 6.1 |

### E. Per node (cały eksperyment)

| Strategia | Node | Pomiary odebrane | Zmiany trybu | Czas do poziomu 20 [s] | Czas życia do FAILED [s] | Czas ACTIVE [s] | Czas DEGRADED [s] | Czas SLEEP [s] |
|---|---|---:|---:|---:|---:|---:|---:|---:|
| Bez zarządzania | node_1 | 151 | 0 | 61.0 | 76.0 | 75.0 | 0.0 | 0.0 |
| Bez zarządzania | node_2 | 151 | 0 | 61.0 | 76.0 | 75.0 | 0.0 | 0.0 |
| Bez zarządzania | node_3 | 151 | 0 | 61.0 | 76.0 | 75.0 | 0.0 | 0.0 |
| Adaptacyjna | node_1 | 137 | 2 | 78.5 | 137.0 | 38.0 | 39.5 | 58.5 |
| Adaptacyjna | node_2 | 137 | 2 | 78.5 | 137.0 | 38.0 | 39.5 | 58.5 |
| Adaptacyjna | node_3 | 137 | 2 | 78.5 | 137.0 | 38.0 | 39.5 | 58.5 |
| Adaptacyjna + rzadszy STATUS w SLEEP | node_1 | 144 | 2 | 78.5 | 157.5 | 38.0 | 39.5 | 79.0 |
| Adaptacyjna + rzadszy STATUS w SLEEP | node_2 | 144 | 2 | 78.5 | 157.5 | 38.0 | 39.5 | 79.0 |
| Adaptacyjna + rzadszy STATUS w SLEEP | node_3 | 144 | 2 | 78.5 | 157.5 | 38.0 | 39.5 | 79.0 |
| Adaptacyjna + priorytet node_1 | node_1 | 143 | 2 | 65.5 | 109.0 | 54.0 | 24.0 | 30.0 |
| Adaptacyjna + priorytet node_1 | node_2 | 137 | 2 | 78.5 | 137.0 | 38.0 | 39.5 | 58.5 |
| Adaptacyjna + priorytet node_1 | node_3 | 137 | 2 | 78.5 | 137.0 | 38.0 | 39.5 | 58.5 |
