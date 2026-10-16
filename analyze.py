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


def read_json(path):
    with open(path, encoding="utf-8") as f:
        return json.load(f)


def load_run(folder):
    run = {"dir": folder, "meta": read_json(os.path.join(folder, "run_meta.json")),
           "mgmt": read_csv(os.path.join(folder, "management_log.csv")),
           "status": read_csv(os.path.join(folder, "status_log.csv")),
           "data": read_csv(os.path.join(folder, "data_log.csv")), "truth": {}, "trace": {}}
    for path in sorted(glob.glob(os.path.join(folder, "*_truth.json"))):
        t = read_json(path)
        run["truth"][t["node_id"]] = t
        run["trace"][t["node_id"]] = read_csv(path.replace("_truth.json", "_energy_trace.csv"))
    return run


def t_sym(ns, meta):
    """Moment na zegarze sinka (ns) -> sekundy symulacji od startu eksperymentu."""
    return (int(ns) - meta["start_ns"]) * 1e-9 * meta["time_scale"]


# --------------------------------------------------------------------------
# metryki (czyste funkcje - testowane w test_wsn.py)
# --------------------------------------------------------------------------
def command_metrics(mgmt, until_ns=None):
    """Czas reakcji i skuteczność poleceń z dziennika zarządzania.
    Czasy w ms RZECZYWISTYCH: opóźnienie UDP i obsługi polecenia nie zależy od przyspieszenia symulacji."""
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
    times = [(acked[c] - first_sent[c]) * 1e-6 for c in acked if c in first_sent]
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
    """Suma czasów expected != reported (z CONFIG_RESTORED i MISMATCH_OPEN_AT_END), w ms RZECZYWISTYCH."""
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
    """Wykrycie awarii noda przez sink.

    Fałszywy alarm = NODE_UNREACHABLE, po którym node się odezwał (NODE_REACHABLE). Właściwe wykrycie to
    OSTATNIE NODE_UNREACHABLE (po nim node już nie wrócił). Zwraca też liczbę fałszywych alarmów."""
    meta = run["meta"]
    ev = [r for r in run["mgmt"] if r["node_id"] == node and r["event_type"] in ("NODE_UNREACHABLE", "NODE_REACHABLE")]
    false_alarms = sum(1 for r in ev if r["event_type"] == "NODE_REACHABLE")
    un = [r for r in ev if r["event_type"] == "NODE_UNREACHABLE"]
    if not un or ev[-1]["event_type"] != "NODE_UNREACHABLE":
        return {"false_alarms": false_alarms, "unreachable_at_s": None, "failed_at_s": None,
                "silence_ms": None, "from_failed_s": None} if false_alarms else None
    last = un[-1]
    silence = [p.split("=")[1] for p in last["details"].split(";") if p.startswith("silence_sim_ms=")]
    failed = [float(r["t_sym_s"]) for r in run["trace"].get(node, []) if r["event"] == "STATE->FAILED"]
    ts = t_sym(int(last["timestamp_ns"]), meta)
    return {"silence_ms": float(silence[0]) if silence else None, "unreachable_at_s": ts,
            "failed_at_s": failed[0] if failed else None,
            "from_failed_s": ts - failed[0] if failed else None, "false_alarms": false_alarms}


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
            "commands": command_metrics(run["mgmt"], until_ns),
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


def _interp(xs, ys, x):
    """Interpolacja liniowa (xs rosnące); poza zakresem - wartość brzegowa."""
    import bisect
    if x <= xs[0]:
        return ys[0]
    if x >= xs[-1]:
        return ys[-1]
    k = bisect.bisect_right(xs, x)
    x0, x1, y0, y1 = xs[k - 1], xs[k], ys[k - 1], ys[k]
    return y0 + (y1 - y0) * (x - x0) / (x1 - x0) if x1 != x0 else y1


def battery_band(run):
    """Średnia i zakres min-max baterii z 3 nodów na wspólnej siatce czasu (z status_log.csv)."""
    meta = run["meta"]
    series = {}
    for n in meta["nodes"]:
        rows = [r for r in run["status"] if r["node_id"] == n]
        series[n] = ([t_sym(r["timestamp_ns"], meta) for r in rows], [float(r["battery_level"]) for r in rows])
    grid = series[meta["nodes"][0]][0]
    mean_, lo, hi = [], [], []
    for x in grid:
        vals = [_interp(xs, ys, x) for xs, ys in series.values()]
        mean_.append(sum(vals) / len(vals)); lo.append(min(vals)); hi.append(max(vals))
    return grid, mean_, lo, hi


def first_command_time(run):
    t = [t_sym(r["timestamp_ns"], run["meta"]) for r in run["mgmt"]
         if r["event_type"] == "COMMAND_SENT" and "duplicate" not in r["details"]]
    return min(t) if t else None


def plot_battery(runs, labels, path, title):
    """Średnia z 3 nodów (linia) i zakres min-max (pas). Różne style linii, więc przykrycie widać."""
    plt = _pyplot()
    fig, ax = plt.subplots(figsize=(9.5, 5.2))
    colors = ["#d62728", "#1f77b4", "#2ca02c", "#9467bd", "#ff7f0e", "#8c564b"]
    styles = ["-", "--", "-.", ":", (0, (5, 1)), (0, (3, 1, 1, 1))]
    for i, (run, label) in enumerate(zip(runs, labels)):
        x, m, lo, hi = battery_band(run)
        ax.fill_between(x, lo, hi, color=colors[i % 6], alpha=0.18, lw=0)
        ax.plot(x, m, color=colors[i % 6], ls=styles[i % 6], lw=2.2, label=label)
        t0 = first_command_time(run)
        if t0 is not None and i == 1:
            ax.axvline(t0, color=colors[i % 6], ls=":", lw=1)
            ax.text(t0 + 0.8, 93, "pierwsze polecenie sinka\n(przed nim obie linie są takie same)",
                    fontsize=8, color=colors[i % 6], va="top")
    ax.axhline(50, color="gray", ls=":", lw=1)
    ax.axhline(20, color="gray", ls=":", lw=1)
    ax.text(ax.get_xlim()[1] * 0.98, 51, "próg DEGRADED (50)", fontsize=8, color="gray", ha="right")
    ax.text(ax.get_xlim()[1] * 0.98, 21, "próg SLEEP / LOW_BATTERY (20)", fontsize=8, color="gray", ha="right")
    ax.set_xlabel("czas symulacji [s]")
    ax.set_ylabel("battery_level (raportowany w STATUS)")
    ax.set_title(title + "\n(linia: średnia z 3 nodów, pas: min-max; nody mają identyczny model)", fontsize=10)
    ax.set_ylim(-2, 102)
    ax.legend(loc="upper right", fontsize=9)
    ax.grid(alpha=0.3)
    fig.tight_layout()
    fig.savefig(path, dpi=140)
    plt.close(fig)


def plot_period(run, path):
    """sample_period_ms w czasie: linia = ślad noda (moment faktycznej zmiany), kropki = to, co zobaczył sink."""
    plt = _pyplot()
    fig, ax = plt.subplots(figsize=(9.5, 4.8))
    n = run["meta"]["nodes"][0]
    tr = run["trace"][n]
    xs = [float(r["t_sym_s"]) for r in tr]
    ax.step(xs, [int(r["sample_period_ms"]) for r in tr], where="post", lw=2.2, color="#1f77b4",
            label=f"{n}: okres w chwili zmiany (ślad noda)")
    rows = [r for r in run["status"] if r["node_id"] == n]
    ax.plot([t_sym(r["timestamp_ns"], run["meta"]) for r in rows], [int(r["sample_period_ms"]) for r in rows],
            "o", ms=3, color="#d62728", label="co raportował STATUS (obserwacja sinka, co 2 s)")
    ax.axhline(500, color="gray", ls=":", label="bez zarządzania (500 ms)")
    failed = [float(r["t_sym_s"]) for r in tr if r["event"] == "STATE->FAILED"]
    if failed:
        ax.axvline(failed[0], color="k", ls="--", lw=0.9)
        ax.text(failed[0] - 1, 1750, "FAILED (bateria 0)", rotation=90, fontsize=8, ha="right", va="center")
    ax.set_xlabel("czas symulacji [s]")
    ax.set_ylabel("sample_period_ms")
    ax.set_title("Okres próbkowania w czasie - strategia adaptacyjna (3 nody mają identyczny przebieg)", fontsize=10)
    ax.set_yticks([500, 1000, 3000])
    ax.set_ylim(0, 3400)
    ax.legend(loc="center left", fontsize=8)
    ax.grid(alpha=0.3)
    fig.tight_layout()
    fig.savefig(path, dpi=140)
    plt.close(fig)


def span(vals, nd=1):
    vals = [v for v in vals if v is not None]
    if not vals:
        return "—"
    lo, hi = min(vals), max(vals)
    return f"{lo:.{nd}f}" if abs(hi - lo) < 10 ** (-nd) else f"{lo:.{nd}f}–{hi:.{nd}f}"


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--runs", nargs="+", required=True, help="foldery przebiegów (kolejność = kolejność w tabeli; dwa pierwsze = wymagane strategie)")
    ap.add_argument("--labels", nargs="+", help="etykiety strategii")
    ap.add_argument("--out", default="wyniki")
    ap.add_argument("--okno-s", type=float, default=100, help="okno obserwacji dla drugiej tabeli [s sym.]")
    ap.add_argument("--testy", nargs="*", default=[], help="foldery przebiegów testowych (polecenia, timeouty, duplikaty)")
    ap.add_argument("--powtorzenia", nargs="*", default=[], help='"Etykieta=dir1,dir2,dir3" - powtórzenia tej samej strategii')
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
              "| Strategia | Wysłane polecenia | ACK | ERROR | Skuteczność | Czas reakcji: średnia [ms rzecz.] | mediana [ms rzecz.] "
              "| maks [ms rzecz.] | Niespójność config [ms rzecz.] | Pakiety zarządcze | Pakiety DATA |",
              "|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|"]
    for l, m in zip(labels, full):
        c, o = m["commands"], m["overhead"]
        lines.append(f"| {l} | {c['commands_sent']} | {c['commands_acked']} | {c['commands_error']} "
                     f"| {fmt(None if c['success_rate'] is None else c['success_rate'] * 100, 1, ' %')} "
                     f"| {fmt(c['response_ms_mean'], 2)} | {fmt(c['response_ms_median'], 2)} | {fmt(c['response_ms_max'], 2)} "
                     f"| {fmt(sum(n['mismatch_ms'] for n in m['nodes'].values()), 1)} "
                     f"| {o['management_packets']} | {o['data_packets']} |")
    lines += ["", "### D. Wykrywanie niedostępności (FAILED -> UNREACHABLE)", "",
              "| Strategia | Node | FAILED w t [s sym.] | UNREACHABLE w t [s sym.] | Cisza przed wykryciem [ms sym.] | FAILED -> UNREACHABLE [s sym.] | Fałszywe UNREACHABLE (node wrócił) |",
              "|---|---|---:|---:|---:|---:|---:|"]
    for l, m in zip(labels, full):
        for n, nm in m["nodes"].items():
            d = nm["detection"]
            if d:
                lines.append(f"| {l} | {n} | {fmt(d['failed_at_s'])} | {fmt(d['unreachable_at_s'])} "
                             f"| {fmt(d['silence_ms'], 0)} | {fmt(d['from_failed_s'])} | {d['false_alarms']} |")
    lines += ["", "### E. Per node (cały eksperyment)", "",
              "| Strategia | Node | Pomiary odebrane | Zmiany trybu | Czas do poziomu 20 [s] | Czas życia do FAILED [s] "
              "| Czas ACTIVE [s] | Czas DEGRADED [s] | Czas SLEEP [s] |", "|---|---|---:|---:|---:|---:|---:|---:|---:|"]
    for l, m in zip(labels, full):
        for n, nm in m["nodes"].items():
            lines.append(f"| {l} | {n} | {nm['received']} | {nm['mode_changes']} | {fmt(nm['time_to_critical_s'])} "
                         f"| {fmt(nm['lifetime_s'])} | {fmt(nm['time_active_s'])} | {fmt(nm['time_degraded_s'])} "
                         f"| {fmt(nm['time_sleep_s'])} |")
    # --- F: powtórzenia (rozrzut) ---
    reps = []
    for spec in a.powtorzenia:
        label, dirs = spec.split("=", 1)
        reps.append((label, [run_metrics(load_run(d)) for d in dirs.split(",")]))
    if reps:
        lines += ["", "### F. Powtórzenia tej samego eksperymentu (min–max z przebiegów)", "",
                  "| Strategia | Przebiegi | Pomiary odebrane (średnia z nodów) | Czas życia do FAILED [s] | Narzut [%] | Skuteczność poleceń [%] | Czas reakcji: średnia [ms rzecz.] |",
                  "|---|---:|---|---|---|---|---|"]
        for label, ms in reps:
            lines.append(f"| {label} | {len(ms)} | {span([mean([n['received'] for n in m['nodes'].values()]) for m in ms], 0)} "
                         f"| {span([mean([n['lifetime_s'] for n in m['nodes'].values()]) for m in ms])} "
                         f"| {span([m['overhead']['overhead'] * 100 for m in ms])} "
                         f"| {span([None if m['commands']['success_rate'] is None else m['commands']['success_rate'] * 100 for m in ms])} "
                         f"| {span([m['commands']['response_ms_mean'] for m in ms], 2)} |")
    # --- T: przebiegi testowe ---
    if a.testy:
        lines += ["", "### T. Przebiegi testowe: polecenia, timeouty, duplikaty", "",
                  "| Przebieg | Wysłane polecenia | ACK | ERROR | Skuteczność (ACK/wysłane) | COMMAND_TIMEOUT | GAVE_UP "
                  "| Duplikaty zignorowane przez nody | Czas reakcji: średnia / maks [ms rzecz.] |", "|---|---:|---:|---:|---:|---:|---:|---:|---|"]
        for d in a.testy:
            r = load_run(d)
            c = command_metrics(r["mgmt"])
            dup = sum(t["commands"]["duplicates_ignored"] for t in r["truth"].values())
            to = sum(1 for x in r["mgmt"] if x["event_type"] == "COMMAND_TIMEOUT" and x["result"] != "GAVE_UP")
            gu = sum(1 for x in r["mgmt"] if x["event_type"] == "COMMAND_TIMEOUT" and x["result"] == "GAVE_UP")
            lines.append(f"| {os.path.basename(d.rstrip('/'))} | {c['commands_sent']} | {c['commands_acked']} | {c['commands_error']} "
                         f"| {fmt(None if c['success_rate'] is None else c['success_rate'] * 100, 1, ' %')} | {to} | {gu} | {dup} "
                         f"| {fmt(c['response_ms_mean'], 1)} / {fmt(c['response_ms_max'], 1)} |")
    with open(os.path.join(a.out, "tabela_wynikow.md"), "w", encoding="utf-8") as f:
        f.write("\n".join(lines) + "\n")
    print("\n".join(lines))

    plot_battery(runs[:2], labels[:2], os.path.join(a.out, "wykres_bateria.png"),
                 "Poziom baterii w czasie: dwie wymagane strategie")
    if len(runs) > 2:
        plot_battery(runs, labels, os.path.join(a.out, "wykres_bateria_warianty.png"),
                     "Poziom baterii w czasie: wszystkie warianty")
    adaptive = next((r for r in runs if r["meta"]["strategy"] == "adaptive"), None)
    if adaptive:
        plot_period(adaptive, os.path.join(a.out, "wykres_okres_probkowania.png"))
    print("Zapisano tabelę i wykresy w", a.out)


if __name__ == "__main__":
    main()
