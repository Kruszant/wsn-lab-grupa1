"""Test mutacyjny: celowo psuje kod (w KOPII) i sprawdza, czy testy to wykryją.

    .venv/bin/python mutation_check.py          # zapisuje wyniki/mutacje.txt

Mutant "zabity" = przynajmniej jeden test jednostkowy zawiódł (dobrze).
Mutant "ocalały" = wszystkie testy przeszły mimo błędu (testy są za słabe) - skrypt kończy się kodem 1.
"""
import os
import shutil
import subprocess
import sys
import tempfile

HERE = os.path.dirname(os.path.abspath(__file__))
UNIT = ["test_wsn.TestWalidacjaPolecenia", "test_wsn.TestEnergia", "test_wsn.TestNodePolecenia",
        "test_wsn.TestSinkManager", "test_wsn.TestMetrykiAnalizy"]

MUTANTS = [
    ("bool przechodzi jako liczba", "wsn_common.py", "isinstance(value, int) and not isinstance(value, bool)", "isinstance(value, int)"),
    ("duplikat polecenia wykonywany ponownie", "node.py", "if cid in self.responses:", "if False:"),
    ("próg baterii: >= zamiast > (50.0 daje ACTIVE)", "wsn_common.py", "if u > to_units(degraded_below):", "if u >= to_units(degraded_below):"),
    ("ERROR nie cofa wersji oczekiwanej", "sink_manager.py", 'e.expected_config_version = m["current_config_version"]', "pass"),
    ("UNREACHABLE nadpisuje reported_state", "sink_manager.py", "e.observed_state = UNREACHABLE", "e.observed_state = e.reported_state = UNREACHABLE"),
    ("zmiana wersji PRZED walidacją", "node.py", "reason = validate_config(msg, self.id, self.config_version, self.state)",
     "self.config_version = msg.get('config_version', self.config_version); reason = validate_config(msg, self.id, self.config_version, self.state)"),
    ("brak kontroli typów pól w sinku", "sink_manager.py", " or bad_types(msg):", ":"),
    ("node bez STATUS nigdy nie jest UNREACHABLE", "sink_manager.py", "ref = e.last_status_ns if e.last_status_ns is not None else self.start_ns", "ref = now if e.last_status_ns is None else e.last_status_ns"),
    ("odtwarzanie konfiguracji bez limitu prób", "sink_manager.py", 'if e.restore_attempts < self.cfg.get("max_restore_attempts", 3):', "if True:"),
    ("czas reakcji mnożony przez time_scale", "analyze.py", "times = [(acked[c] - first_sent[c]) * 1e-6 for c in acked if c in first_sent]", "times = [(acked[c] - first_sent[c]) * 1e-6 * 10 for c in acked if c in first_sent]"),
]


def main():
    lines, survived = [], 0
    for name, fname, old, new in MUTANTS:
        tmp = tempfile.mkdtemp()
        try:
            for f in os.listdir(HERE):
                if f.endswith(".py"):
                    shutil.copy(os.path.join(HERE, f), tmp)
            os.symlink(os.path.join(HERE, "config"), os.path.join(tmp, "config"))
            path = os.path.join(tmp, fname)
            src = open(path, encoding="utf-8").read()
            if old not in src:
                lines.append(f"POMINIĘTY (brak wzorca w {fname}): {name}")
                continue
            open(path, "w", encoding="utf-8").write(src.replace(old, new, 1))
            r = subprocess.run([sys.executable, "-m", "unittest"] + UNIT, cwd=tmp, capture_output=True, text=True)
            failed = [l.split(" ")[1] for l in r.stderr.splitlines() if l.startswith(("FAIL:", "ERROR:"))]
            if r.returncode != 0:
                lines.append(f"ZABITY   {name:55} -> {len(failed)} test(ów), np. {failed[0] if failed else '?'}")
            else:
                survived += 1
                lines.append(f"OCALAŁY  {name}")
        finally:
            shutil.rmtree(tmp, ignore_errors=True)
    lines.append("")
    lines.append(f"Mutantów: {len(MUTANTS)}, zabitych: {len(MUTANTS) - survived}, ocalałych: {survived}")
    os.makedirs(os.path.join(HERE, "wyniki"), exist_ok=True)
    with open(os.path.join(HERE, "wyniki", "mutacje.txt"), "w", encoding="utf-8") as f:
        f.write("\n".join(lines) + "\n")
    print("\n".join(lines))
    return 1 if survived else 0


if __name__ == "__main__":
    sys.exit(main())
