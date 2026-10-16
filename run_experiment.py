"""Uruchamia jeden eksperyment: sink-manager + trzy nody jako OSOBNE PROCESY (UDP, localhost).

    python run_experiment.py --sink config/sink_adaptacyjna.json --out wyniki/adaptacyjna
    python run_experiment.py --sink config/rdzen/sink.json --out wyniki/test_rdzenia
    python run_experiment.py --sink config/strat/sink.json --out wyniki/test_strat

Wszystkie procesy dostają TEN SAM time_scale i duration_s (przekazane argumentami), żeby
nie dało się ich przypadkiem rozjechać. To samo można zrobić ręcznie w czterech terminalach:
    python sink_manager.py --config config/sink_adaptacyjna.json --output-dir wyniki/x
    python node.py --config config/node_1.json --output-dir wyniki/x   (i node_2, node_3)
"""
import argparse
import json
import os
import subprocess
import sys
import time

HERE = os.path.dirname(os.path.abspath(__file__))


def run(sink_cfg, out_dir, time_scale=None, duration_s=None, node_cfgs=None, quiet=True, status_period_ms=None):
    with open(os.path.join(HERE, sink_cfg) if not os.path.isabs(sink_cfg) else sink_cfg) as f:
        base = json.load(f)
    scale = time_scale or base["time_scale"]
    duration = duration_s or base["duration_s"]
    out_dir = os.path.abspath(out_dir)
    os.makedirs(out_dir, exist_ok=True)
    common = ["--output-dir", out_dir, "--time-scale", str(scale), "--duration-s", str(duration)]
    node_extra, sink_extra = [], []
    if status_period_ms:                                # ten sam okres STATUS dla nodów i założenie sinka
        node_extra = ["--status-period-ms", str(status_period_ms)]
        sink_extra = ["--default-status-period-ms", str(status_period_ms)]
    py = sys.executable
    out = subprocess.DEVNULL if quiet else None
    procs = [subprocess.Popen([py, os.path.join(HERE, "sink_manager.py"), "--config",
                               os.path.join(HERE, sink_cfg)] + common, cwd=HERE, stdout=out)]
    time.sleep(0.6)                                    # sink musi już słuchać
    # nody: z argumentu, a w razie braku - lista `node_configs` zapisana w konfiguracji sinka
    for cfg in (node_cfgs or base.get("node_configs") or
                ["config/node_1.json", "config/node_2.json", "config/node_3.json"]):
        procs.append(subprocess.Popen([py, os.path.join(HERE, "node.py"), "--config",
                                       os.path.join(HERE, cfg)] + common + node_extra, cwd=HERE, stdout=out))
    deadline = time.time() + duration / scale + 20
    for p in procs:
        try:
            p.wait(timeout=max(1, deadline - time.time()))
        except subprocess.TimeoutExpired:
            p.kill()
    return out_dir


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--sink", required=True)
    ap.add_argument("--out", required=True)
    ap.add_argument("--time-scale", type=float)
    ap.add_argument("--duration-s", type=float)
    ap.add_argument("--nodes", nargs=3, metavar="CFG", help="3 konfiguracje nodów (domyślnie: `node_configs` z konfiguracji sinka)")
    ap.add_argument("--status-period-ms", type=int, help="nadpisuje okres STATUS wszystkich nodów")
    a = ap.parse_args()
    print("Wyniki w:", run(a.sink, a.out, a.time_scale, a.duration_s, node_cfgs=a.nodes, quiet=False,
                                  status_period_ms=a.status_period_ms))
