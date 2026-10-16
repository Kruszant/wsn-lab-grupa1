"""Odtwarza WSZYSTKIE wyniki jedną komendą:   .venv/bin/python run_all.py

Uruchamia kolejno (każdy to osobne 4 procesy UDP: sink-manager + 3 nody), potem analiza:
  - wymagane strategie: bez zarządzania, adaptacyjna (z 3 powtórzeniami każda),
  - warianty: rzadszy STATUS w SLEEP, priorytet node_1, wariant B kosztu SLEEP,
  - bezpośredni test STATUS co 1 s i 4 s (bez zarządzania) - pytanie 3,
  - testy: wspólny rdzeń (ACK/ERROR/duplikat) i ścieżka ze stratami (timeouty, GAVE_UP).
Czas: ok. 5 minut (symulacja jest 10x szybsza od czasu rzeczywistego).
"""
import os
import shutil
import subprocess
import sys
import time

import run_experiment

HERE = os.path.dirname(os.path.abspath(__file__))
W = os.path.join(HERE, "wyniki")

# (folder wyniku, konfiguracja sinka, dodatkowe argumenty run())
RUNS = [
    ("bez_zarzadzania", "config/sink_bez_zarzadzania.json", {}),
    ("adaptacyjna", "config/sink_adaptacyjna.json", {}),
    ("adaptacyjna_status", "config/sink_adaptacyjna_status.json", {}),
    ("adaptacyjna_priorytet", "config/sink_adaptacyjna_priorytet.json", {}),
    ("wariant_B_adaptacyjna", "config/wariant_B/sink_adaptacyjna.json", {}),
    ("status_1s", "config/status_1s/sink.json", {}),
    ("status_4s", "config/status_4s/sink.json", {}),
    ("powtorzenia/bez_2", "config/sink_bez_zarzadzania.json", {}),
    ("powtorzenia/bez_3", "config/sink_bez_zarzadzania.json", {}),
    ("powtorzenia/adapt_2", "config/sink_adaptacyjna.json", {}),
    ("powtorzenia/adapt_3", "config/sink_adaptacyjna.json", {}),
    ("test_rdzenia", "config/rdzen/sink.json", {}),
    ("test_strat", "config/strat/sink.json", {}),
]
LABELS = ["Bez zarządzania (STATUS 2 s)", "Adaptacyjna", "Adaptacyjna + rzadszy STATUS w SLEEP",
          "Adaptacyjna + priorytet node_1", "Adaptacyjna, wariant B kosztu SLEEP",
          "Bez zarządzania, STATUS 1 s", "Bez zarządzania, STATUS 4 s"]


def main():
    t0 = time.time()
    only_analysis = "--tylko-analiza" in sys.argv          # pomija symulacje, liczy tabelę i wykresy z zapisanych danych
    for name, sink, extra in ([] if only_analysis else RUNS):
        out = os.path.join(W, name)
        shutil.rmtree(out, ignore_errors=True)
        run_experiment.run(sink, out, **extra)
        print(f"[{time.time() - t0:5.0f}s] gotowe: {name}", flush=True)
    d = lambda n: os.path.join("wyniki", n)
    cmd = [sys.executable, os.path.join(HERE, "analyze.py"), "--out", "wyniki", "--okno-s", "100",
           "--runs"] + [d(n) for n, _, _ in RUNS[:7]] + ["--labels"] + LABELS + [
           "--testy", d("test_rdzenia"), d("test_strat"),
           "--powtorzenia",
           f"Bez zarządzania={d('bez_zarzadzania')},{d('powtorzenia/bez_2')},{d('powtorzenia/bez_3')}",
           f"Adaptacyjna={d('adaptacyjna')},{d('powtorzenia/adapt_2')},{d('powtorzenia/adapt_3')}"]
    subprocess.run(cmd, cwd=HERE, check=True, stdout=subprocess.DEVNULL)
    print("Tabela: wyniki/tabela_wynikow.md, wykresy: wyniki/wykres_*.png")


if __name__ == "__main__":
    main()
