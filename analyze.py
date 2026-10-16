"""Analiza wyników - WYŁĄCZNIE z zapisanych plików (CSV / JSON), bez dostępu do żywych procesów.

    python analyze.py --runs wyniki/bez_zarzadzania wyniki/adaptacyjna --out wyniki --okno-s 100

Wejście (z każdego folderu przebiegu): management_log.csv, status_log.csv, data_log.csv,
run_meta.json oraz <node_id>_truth.json i <node_id>_energy_trace.csv zapisane przez nody.
Wyjście: metrics.json w każdym folderze, tabela_wynikow.md oraz wykresy PNG.

DEFINICJE METRYK (czas zawsze w sekundach / ms SYMULACJI = czas rzeczywisty * time_scale):
  command_response_time = czas odbioru ACK - czas PIERWSZEGO wysłania polecenia (zegar sinka)
  command_success_rate  = polecenia z ACK(APPLIED) / wszystkie wysłane polecenia (unikatowe command_id)
  management_overhead   = pakiety zarządcze / wszystkie pakiety widziane przez sink
                          (zarządcze: STATUS, CONFIG, COMMAND, ACK, ERROR, ALERT - także ponowienia CONFIG;
                           wszystkie: zarządcze + DATA)
  availability          = czas, w którym node jest osiągalny I raportuje ACTIVE/DEGRADED/SLEEP, / czas eksperymentu
  config_mismatch_time  = suma okresów, gdy expected_config_version != reported_config_version
"""
import argparse
import csv
import glob
import json
import os
import statistics


def _pyplot():
    """matplotlib ładujemy dopiero przy rysowaniu - metryki i testy działają bez niego."""
    import matplotlib
    matplotlib.use("Agg")                  # zapis do pliku, bez okna
    import matplotlib.pyplot as plt
    return plt

MGMT_EVENTS = ("COMMAND_SENT", "STATUS_RECEIVED", "ALERT_RECEIVED", "ACK_RECEIVED", "ERROR_RECEIVED")
AVAILABLE_STATES = ("ACTIVE", "DEGRADED", "SLEEP")


# --------------------------------------------------------------------------
# wczytywanie
# --------------------------------------------------------------------------
def read_csv(path):
    with open(path, encoding="utf-8") as f:
        return list(csv.DictReader(f))


def load_run(folder):
    run = {"dir": folder, "meta": json.load(open(os.path.join(folder, "run_meta.json"), encoding="utf-8")),
           "mgmt": read_csv(os.path.join(folder, "management_log.csv")),
           "status": read_csv(os.path.join(folder, "status_log.csv")),
           "data": read_csv(os.path.join(folder, "data_log.csv")), "truth": {}, "trace": {}}
    for path in sorted(glob.glob(os.path.join(folder, "*_truth.json"))):
        t = json.load(open(path, encoding="utf-8"))
        run["truth"][t["node_id"]] = t
        run["trace"][t["node_id"]] = read_csv(path.replace("_truth.json", "_energy_trace.csv"))
    return run


def t_sym(ns, meta):
    """Moment na zegarze sinka (ns) -> sekundy symulacji od startu eksperymentu."""
    return (int(ns) - meta["start_ns"]) * 1e-9 * meta["time_scale"]


# --------------------------------------------------------------------------
# metryki (czyste funkcje - testowane w test_wsn.py)
# --------------------------------------------------------------------------
def command_metrics(mgmt, scale, until_ns=None):
    """Czas reakcji i skuteczność poleceń z dziennika zarządzania."""
    first_sent, acked, errored = {}, {}, {}
    for r in mgmt:
        if until_ns is not None and int(r["timestamp_ns"]) > until_ns:
            continue
        cid, ev, det = r["command_id"], r["event_type"], r["details"]
        if not cid:
            continue
        if ev == "COMMAND_SENT" and "duplicate_test_resend" not in det:
            first_sent.setdefault(cid, int(r["timestamp_ns"]))        # PIERWSZE wysłanie
        elif ev == "ACK_RECEIVED" and "duplicate" not in det and "unknown" not in det:
            acked.setdefault(cid, int(r["timestamp_ns"]))
        elif ev == "ERROR_RECEIVED" and "duplicate" not in det and "unknown" not in det:
            errored.setdefault(cid, int(r["timestamp_ns"]))
    times = [(acked[c] - first_sent[c]) * 1e-6 * scale for c in acked if c in first_sent]
    sent = len(first_sent)
    return {"commands_sent": sent, "commands_acked": len(acked), "commands_error": len(errored),
            "success_rate": len(acked) / sent if sent else None,
            "response_ms_mean": statistics.mean(times) if times else None,
            "response_ms_median": statistics.median(times) if times else None,
            "response_ms_max": max(times) if times else None}


def management_overhead(mgmt, data, until_ns=None):
    keep = (lambda r: True) if until_ns is None else (lambda r: int(r["timestamp_ns"]) <= until_ns)
    m = sum(1 for r in mgmt if r["event_type"] in MGMT_EVENTS and keep(r))
    d = sum(1 for r in data if keep(r))
    return {"management_packets": m, "data_packets": d,
            "overhead": m / (m + d) if (m + d) else None}


def mismatch_time_ms(mgmt, node=None):
    """Suma czasów expected != reported (z CONFIG_RESTORED i MISMATCH_OPEN_AT_END), w ms symulacji."""
    total = 0.0
    for r in mgmt:
        if r["event_type"] in ("CONFIG_RESTORED", "MISMATCH_OPEN_AT_END") and (node is None or r["node_id"] == node):
            for part in r["details"].split(";"):
                if part.startswith("duration_ms="):
                    total += float(part.split("=")[1])
    return total


def availability(status_rows, mgmt, node, meta, end_s):
    """Ułamek czasu [0, end_s], gdy node jest osiągalny i raportuje stan pracy."""
    ev = []
    for r in status_rows:
        if r["node_id"] == node:
            ev.append((int(r["timestamp_ns"]), "state", r["operating_state"]))
    for r in mgmt:
        if r["node_id"] == node and r["event_type"] in ("NODE_UNREACHABLE", "NODE_REACHABLE"):
            ev.append((int(r["timestamp_ns"]), r["event_type"], ""))
    ev.sort(key=lambda x: x[0])
    state, reachable, last_t, up = None, True, 0.0, 0.0
    for ns, kind, val in ev:
        t = min(max(t_sym(ns, meta), 0.0), end_s)
        if state in AVAILABLE_STATES and reachable:
            up += t - last_t
        last_t = t
        if kind == "state":
            state = val
        else:
            reachable = kind == "NODE_REACHABLE"
    if state in AVAILABLE_STATES and reachable:
        up += end_s - last_t
    return up / end_s if end_s else None


def state_times(trace, until_s):
    """Czas w stanach do chwili until_s (z śladu energii zapisanego przez node)."""
    acc, prev_t, prev_state = {}, 0.0, "STARTING"
    for r in trace:
        t = min(float(r["t_sym_s"]), until_s)
        acc[prev_state] = acc.get(prev_state, 0.0) + max(0.0, t - prev_t)
        prev_t, prev_state = t, r["state"]
        if float(r["t_sym_s"]) >= until_s:
            break
    else:
        acc[prev_state] = acc.get(prev_state, 0.0) + max(0.0, until_s - prev_t)
    return acc


def battery_at(trace, t_s):
    b = None
    for r in trace:
        if float(r["t_sym_s"]) > t_s:
            break
        b = float(r["battery_level"])
    return b


def detection_times(run, node):
    """Czas wykrycia niedostępności: od ostatniego STATUS do NODE_UNREACHABLE (ms sym.)
    oraz od przejścia noda w FAILED (z jego śladu) do NODE_UNREACHABLE (s sym.)."""
    meta = run["meta"]
    un = [r for r in run["mgmt"] if r["node_id"] == node and r["event_type"] == "NODE_UNREACHABLE"]
    if not un:
        return None
    ts = int(un[0]["timestamp_ns"])
    silence = [p.split("=")[1] for p in un[0]["details"].split(";") if p.startswith("silence_ms=")]
    failed = [float(r["t_sym_s"]) for r in run["trace"].get(node, []) if r["event"] == "STATE->FAILED"]
    return {"silence_ms": float(silence[0]) if silence else None,
            "unreachable_at_s": t_sym(ts, meta),
            "failed_at_s": failed[0] if failed else None,
            "from_failed_s": t_sym(ts, meta) - failed[0] if failed else None}


# --------------------------------------------------------------------------
# metryki przebiegu
# --------------------------------------------------------------------------
def run_metrics(run, window_s=None):
    """Metryki całego przebiegu; window_s = obserwacja do danej chwili (np. 100 s) zamiast do końca."""
    meta = run["meta"]
    end_s = min(window_s, meta["duration_s"]) if window_s else meta["duration_s"]
    until_ns = meta["start_ns"] + int(end_s / meta["time_scale"] * 1e9)
    nodes = {}
    for n in meta["nodes"]:
        truth, trace = run["truth"].get(n, {}), run["trace"].get(n, [])
        received = [r for r in run["data"] if r["node_id"] == n and not int(r["duplicate"])
                    and int(r["timestamp_ns"]) <= until_ns]
        generated = sum(1 for r in trace if r["event"] == "DATA" and float(r["t_sym_s"]) <= end_s)
        st = state_times(trace, end_s)
        changes = [c for c in truth.get("mode_changes", []) if c["t_s"] <= end_s]
        fail_t = [float(r["t_sym_s"]) for r in trace if r["event"] == "STATE->FAILED"]
        nodes[n] = {"final_battery": battery_at(trace, end_s), "generated": generated,
                    "received": len(received), "mode_changes": len(changes),
                    "time_active_s": st.get("ACTIVE", 0.0), "time_degraded_s": st.get("DEGRADED", 0.0),
                    "time_sleep_s": st.get("SLEEP", 0.0), "time_failed_s": st.get("FAILED", 0.0),
                    "time_to_critical_s": truth.get("time_to_critical_s") if (truth.get("time_to_critical_s") or 0) <= end_s else None,
                    "lifetime_s": fail_t[0] if fail_t and fail_t[0] <= end_s else None,
                    "availability": availability(run["status"], run["mgmt"], n, meta, end_s),
                    "mismatch_ms": mismatch_time_ms(run["mgmt"], n),
                    "detection": detection_times(run, n),
                    "commands": truth.get("commands")}
    return {"strategy": meta["strategy"], "window_s": end_s, "nodes": nodes,
            "commands": command_metrics(run["mgmt"], meta["time_scale"], until_ns),
            "overhead": management_overhead(run["mgmt"], run["data"], until_ns),
            "counts": meta["counts"]}


def mean(vals):
    vals = [v for v in vals if v is not None]
    return statistics.mean(vals) if vals else None


def fmt(v, nd=1, suffix=""):
    return "—" if v is None else f"{v:.{nd}f}{suffix}"


# --------------------------------------------------------------------------
# tabele i wykresy
# --------------------------------------------------------------------------
def table_row(label, m):
    ns = list(m["nodes"].values())
    return (f"| {label} | {fmt(mean(n['final_battery']for n in ns))} | {fmt(mean(n['received']for n in ns), 0)} "
            f"| {fmt(mean(n['generated']for n in ns), 0)} | {fmt(mean(n['mode_changes']for n in ns), 0)} "
            f"| {fmt(mean(n['time_active_s']for n in ns))} | {fmt(mean(n['time_degraded_s']for n in ns))} "
            f"| {fmt(mean(n['time_sleep_s']for n in ns))} | {fmt(m['overhead']['overhead'] * 100, 1, ' %')} "
            f"| {fmt(mean(n['lifetime_s']for n in ns), 1)} | {fmt(mean(n['time_to_critical_s']for n in ns), 1)} "
            f"| {fmt(mean(n['availability']for n in ns) * 100, 1, ' %')} |")


HEADER = ("| Strategia | Energia końcowa | Pomiary odebrane | Pomiary wygenerowane | Zmiany trybu | Czas ACTIVE [s] "
          "| Czas DEGRADED [s] | Czas SLEEP [s] | Narzut | Czas życia do FAILED [s] | Czas do poziomu 20 [s] "
          "| Dostępność |\n|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|")


def plot_battery(runs, labels, path):
    plt = _pyplot()
    fig, ax = plt.subplots(figsize=(9, 5))
    colors = ["#d62728", "#1f77b4", "#2ca02c", "#9467bd", "#ff7f0e"]
    for i, (run, label) in enumerate(zip(runs, labels)):
        for j, n in enumerate(run["meta"]["nodes"]):
            rows = [r for r in run["status"] if r["node_id"] == n]
            ax.plot([t_sym(r["timestamp_ns"], run["meta"]) for r in rows],
                    [float(r["battery_level"]) for r in rows], color=colors[i % 5],
                    lw=2.2 if j == 0 else 1.0, alpha=1.0 if j == 0 else 0.6,
                    label=label if j == 0 else None)
    ax.axhline(50, color="gray", ls=":", lw=1)
    ax.axhline(20, color="gray", ls=":", lw=1)
    ax.text(1, 51, "próg DEGRADED (50)", fontsize=8, color="gray")
    ax.text(1, 21, "próg SLEEP / LOW_BATTERY (20)", fontsize=8, color="gray")
    ax.set_xlabel("czas symulacji [s]")
    ax.set_ylabel("battery_level (raportowany w STATUS)")
    ax.set_title("Poziom baterii w czasie (grube linie: node_1, cienkie: node_2 i node_3)")
    ax.set_ylim(-2, 102)
    ax.legend()
    ax.grid(alpha=0.3)
    fig.tight_layout()
    fig.savefig(path, dpi=140)
    plt.close(fig)


def plot_period(run, path, reference=None):
    plt = _pyplot()
    fig, ax = plt.subplots(figsize=(9, 4.5))
    failed_marked = False
    for j, n in enumerate(run["meta"]["nodes"]):
        rows = [r for r in run["status"] if r["node_id"] == n]
        ax.step([t_sym(r["timestamp_ns"], run["meta"]) for r in rows],
                [int(r["sample_period_ms"]) for r in rows], where="post", lw=2.2 if j == 0 else 1.0,
                alpha=1.0 if j == 0 else 0.6, label=n)
        for r in rows:
            if r["operating_state"] == "FAILED":
                ax.axvline(t_sym(r["timestamp_ns"], run["meta"]), color="k", ls="--", lw=0.8)
                if not failed_marked:                      # jeden podpis zamiast trzech nałożonych
                    ax.text(t_sym(r["timestamp_ns"], run["meta"]) - 1, 3100, "FAILED (bateria 0)",
                            fontsize=8, ha="right")
                    failed_marked = True
                break
    if reference is not None:
        ax.axhline(reference, color="gray", ls=":", label="bez zarządzania (500 ms)")
    ax.set_xlabel("czas symulacji [s]")
    ax.set_ylabel("sample_period_ms (raportowany w STATUS)")
    ax.set_title("Okres próbkowania w czasie - strategia adaptacyjna")
    ax.set_yticks([500, 1000, 3000])
    ax.legend()
    ax.grid(alpha=0.3)
    fig.tight_layout()
    fig.savefig(path, dpi=140)
    plt.close(fig)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--runs", nargs="+", required=True, help="foldery przebiegów (kolejność = kolejność w tabeli)")
    ap.add_argument("--labels", nargs="+", help="etykiety strategii")
    ap.add_argument("--out", default="wyniki")
    ap.add_argument("--okno-s", type=float, default=100, help="okno obserwacji dla drugiej tabeli [s sym.]")
    a = ap.parse_args()
    runs = [load_run(d) for d in a.runs]
    labels = a.labels or [os.path.basename(d.rstrip("/")) for d in a.runs]
    os.makedirs(a.out, exist_ok=True)

    full = [run_metrics(r) for r in runs]
    win = [run_metrics(r, a.okno_s) for r in runs]
    for r, m, w in zip(runs, full, win):
        with open(os.path.join(r["dir"], "metrics.json"), "w", encoding="utf-8") as f:
            json.dump({"full": m, "window": w}, f, indent=2, ensure_ascii=False)

    lines = [f"### A. Do końca eksperymentu ({full[0]['window_s']:.0f} s symulacji, średnia z 3 nodów)", "", HEADER]
    lines += [table_row(l, m) for l, m in zip(labels, full)]
    lines += ["", f"### B. Okno obserwacji {a.okno_s:.0f} s symulacji (ten sam czas dla wszystkich strategii)", "", HEADER]
    lines += [table_row(l, m) for l, m in zip(labels, win)]
    lines += ["", "### C. Polecenia i zarządzanie (cały eksperyment)", "",
              "| Strategia | Wysłane polecenia | ACK | ERROR | Skuteczność | Czas reakcji: średnia [ms sym.] | mediana [ms sym.] "
              "| maks [ms sym.] | Niespójność config [ms sym.] | Pakiety zarządcze | Pakiety DATA |",
              "|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|"]
    for l, m in zip(labels, full):
        c, o = m["commands"], m["overhead"]
        lines.append(f"| {l} | {c['commands_sent']} | {c['commands_acked']} | {c['commands_error']} "
                     f"| {fmt(None if c['success_rate'] is None else c['success_rate'] * 100, 1, ' %')} "
                     f"| {fmt(c['response_ms_mean'])} | {fmt(c['response_ms_median'])} | {fmt(c['response_ms_max'])} "
                     f"| {fmt(sum(n['mismatch_ms'] for n in m['nodes'].values()))} "
                     f"| {o['management_packets']} | {o['data_packets']} |")
    lines += ["", "### D. Wykrywanie niedostępności (FAILED -> UNREACHABLE)", "",
              "| Strategia | Node | FAILED w t [s] | UNREACHABLE w t [s] | Cisza przed wykryciem [ms] | FAILED -> UNREACHABLE [s] |",
              "|---|---|---:|---:|---:|---:|"]
    for l, m in zip(labels, full):
        for n, nm in m["nodes"].items():
            d = nm["detection"]
            if d:
                lines.append(f"| {l} | {n} | {fmt(d['failed_at_s'])} | {fmt(d['unreachable_at_s'])} "
                             f"| {fmt(d['silence_ms'], 0)} | {fmt(d['from_failed_s'])} |")
    lines += ["", "### E. Per node (cały eksperyment)", "",
              "| Strategia | Node | Pomiary odebrane | Zmiany trybu | Czas do poziomu 20 [s] | Czas życia do FAILED [s] "
              "| Czas ACTIVE [s] | Czas DEGRADED [s] | Czas SLEEP [s] |", "|---|---|---:|---:|---:|---:|---:|---:|---:|"]
    for l, m in zip(labels, full):
        for n, nm in m["nodes"].items():
            lines.append(f"| {l} | {n} | {nm['received']} | {nm['mode_changes']} | {fmt(nm['time_to_critical_s'])} "
                         f"| {fmt(nm['lifetime_s'])} | {fmt(nm['time_active_s'])} | {fmt(nm['time_degraded_s'])} "
                         f"| {fmt(nm['time_sleep_s'])} |")
    with open(os.path.join(a.out, "tabela_wynikow.md"), "w", encoding="utf-8") as f:
        f.write("\n".join(lines) + "\n")
    print("\n".join(lines))

    plot_battery(runs, labels, os.path.join(a.out, "wykres_bateria.png"))
    adaptive = next((r for r in runs if r["meta"]["strategy"] == "adaptive"), None)
    if adaptive:
        plot_period(adaptive, os.path.join(a.out, "wykres_okres_probkowania.png"), reference=500)
    print("Zapisano tabelę i wykresy w", a.out)


if __name__ == "__main__":
    main()
