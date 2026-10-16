"""NODE - punkt pomiarowy z zarządzaniem energią (Grupa 1, temat 2).

Jeden program uruchamiany z trzema konfiguracjami:
    python node.py --config config/node_1.json
    python node.py --config config/node_2.json
    python node.py --config config/node_3.json

Co robi node:
  * mierzy (sinusoida + szum) co `sample_period_ms` i wysyła DATA do sinka (UDP),
  * co `status_period_ms` wysyła STATUS (stan, bateria, okres próbkowania, wersja konfiguracji),
  * słucha poleceń CONFIG na własnym porcie: waliduje -> wykonuje -> odpowiada ACK / ERROR,
  * duplikat command_id NIE jest wykonywany ponownie (node odsyła zapamiętaną odpowiedź),
  * `config_version` rośnie dopiero po poprawnym wykonaniu polecenia,
  * liczy abstrakcyjną energię (koszty z konfiguracji), przy 20 wysyła jednorazowy ALERT
    LOW_BATTERY, a po wyczerpaniu przechodzi w stan FAILED (i milknie),
  * na końcu zapisuje "prawdę o sobie" (<node_id>_truth.json, <node_id>_energy_trace.csv) do porównania
    z tym, co zaobserwował sink.

Stany: STARTING -> ACTIVE <-> DEGRADED <-> SLEEP (zmiana tylko poleceniem sinka),
       dowolny stan pracy -> FAILED (bateria 0), na końcu eksperymentu -> STOPPED.
Node sam NIE zmienia trybu pracy wg progów energii - to decyzja sink-managera,
podejmowana na podstawie obserwowanego STATUS/ALERT.
"""
import argparse
import csv
import json
import math
import os
import random
import socket
import threading

from wsn_common import (HOST, OPERATING_STATES, SimClock, decode, encode, load_config, now_ns,
                        to_units, validate_config)

REQUIRED = {"node_id": str, "port": int, "sink_port": int, "time_scale": (int, float),
            "duration_s": (int, float), "seed": int, "output_dir": str,
            "sample_period_ms": int, "status_period_ms": int, "startup_ms": int,
            "signal": dict, "unit": str, "energy": dict}


class Node:
    def __init__(self, cfg: dict, send=None):
        self.cfg = cfg
        self.id = cfg["node_id"]
        self.clock = SimClock(cfg["time_scale"], now_ns())
        self.rng = random.Random(cfg["seed"])                  # powtarzalny szum pomiarów
        self.hook_rng = random.Random(cfg["seed"] + 1000)      # losowe gubienie (tylko testy)
        self.hooks = cfg.get("test_hooks", {})
        self.lock = threading.RLock()
        self.sock = None
        self.stop_event = threading.Event()
        self._send_override = send                              # wstrzykiwane w testach

        e = cfg["energy"]
        self.cost = {k: to_units(e[k]) for k in ("generate", "send_data", "send_status",
                                                  "receive_command", "sleep_cycle")}
        self.battery_units = to_units(e["initial"])
        self.alert_units = to_units(e["low_battery_threshold"])
        self.alert_threshold = e["low_battery_threshold"]
        self.alert_sent = False                                  # LOW_BATTERY tylko raz
        self.alert_due = False
        self.failed_due = False
        self.time_to_critical_s = None

        # stan i konfiguracja (config_version startuje od 1)
        self.state = "STARTING"
        self.config_version = 1
        self.sample_ms = cfg["sample_period_ms"]
        self.status_ms = cfg["status_period_ms"]
        self.initial_state = cfg.get("initial_operating_state", "ACTIVE")
        self.sequence = 0
        self.status_sequence = 0
        self.sent_packets = 0                                    # wysłane DATA
        self.responses = {}                                      # command_id -> zapamiętana odpowiedź
        self.stats = {"commands_received": 0, "commands_applied": 0, "commands_rejected": 0,
                      "duplicates_ignored": 0, "test_dropped_commands": 0, "test_dropped_replies": 0}
        self.state_time = {s: 0.0 for s in ("STARTING", "ACTIVE", "DEGRADED", "SLEEP", "FAILED", "STOPPED")}
        self.state_enter_s = 0.0
        self.mode_changes = []                                   # {t_s, from, to}
        self.trace = []                                          # (t_s, battery, state, sample_ms, event)
        self.next_sample_ns = self.next_status_ns = 0

    # ------------------------------------------------------------------ pomoc
    @property
    def battery_level(self) -> float:
        return self.battery_units / 1000.0

    def _t(self) -> float:
        return self.clock.sim_s(now_ns())

    def _trace(self, event: str):
        self.trace.append((round(self._t(), 3), self.battery_level, self.state, self.sample_ms, event))

    def _send(self, msg: dict, drop_key: str = None):
        """Wysyła datagram do sinka. drop_key = opcjonalny hak testowy (symulacja strat)."""
        if drop_key and self.hook_rng.random() < self.hooks.get(drop_key, 0.0):
            self.stats["test_dropped_replies"] += 1
            return
        if self._send_override:
            self._send_override(msg)
        elif self.sock:
            try:
                self.sock.sendto(encode(msg), (self.cfg.get("sink_host", HOST), self.cfg["sink_port"]))
            except OSError:
                pass

    def _set_state(self, new: str):
        """Jedyne miejsce zmiany stanu (maszyna stanów) + księgowanie czasu w stanach."""
        t = self._t()
        self.state_time[self.state] += t - self.state_enter_s
        self.state_enter_s = t
        if new != self.state:
            if self.state in OPERATING_STATES and new in OPERATING_STATES:
                self.mode_changes.append({"t_s": round(t, 3), "from": self.state, "to": new})
            self.state = new
            self._trace(f"STATE->{new}")

    # ------------------------------------------------------------------ energia
    def charge(self, kind: str):
        """Odejmuje koszt operacji (liczby całkowite!). Flagi alarmu/awarii obsługuje _post()."""
        self.battery_units = max(0, self.battery_units - self.cost[kind])
        if not self.alert_sent and self.battery_units <= self.alert_units:
            self.alert_sent = True                      # "pierwsze osiągnięcie 20" -> tylko raz
            self.alert_due = True
            self.time_to_critical_s = round(self._t(), 3)
        if self.battery_units == 0 and self.state in OPERATING_STATES:
            self.failed_due = True

    def _post(self):
        """Po operacji: wyślij zaległy ALERT i obsłuż wyczerpanie baterii (FAILED)."""
        if self.alert_due:
            self.alert_due = False
            self._send({"type": "ALERT", "node_id": self.id, "alert_type": "LOW_BATTERY",
                        "value": self.battery_level, "threshold": self.alert_threshold,
                        "timestamp_ns": now_ns()})
        if self.failed_due and self.state in OPERATING_STATES:
            self.failed_due = False
            self._set_state("FAILED")
            self._emit_status()                         # ostatni raport "FAILED", potem cisza

    # ------------------------------------------------------------------ nadawanie
    def _emit_status(self):
        self.status_sequence += 1
        self._send({"type": "STATUS", "node_id": self.id, "status_sequence": self.status_sequence,
                    "timestamp_ns": now_ns(), "operating_state": self.state,
                    "battery_level": self.battery_level, "sample_period_ms": self.sample_ms,
                    "sent_packets": self.sent_packets, "config_version": self.config_version})

    def send_status(self):
        with self.lock:
            if self.state not in OPERATING_STATES:
                return
            self.charge("send_status")
            if self.failed_due:                         # bateria padła na wysyłaniu STATUS
                self._post()
                return
            self._emit_status()
            self._trace("STATUS")
            self._post()

    def do_sample(self):
        with self.lock:
            if self.state not in OPERATING_STATES:
                return
            self.charge("generate")
            if self.state == "SLEEP":
                self.charge("sleep_cycle")              # narzut cyklu uśpienia (patrz README)
            if self.failed_due:
                self._post()
                return
            self.sequence += 1
            sg = self.cfg["signal"]
            value = (sg["base"] + sg["amplitude"] * math.sin(2 * math.pi * self._t() / sg["period_s"])
                     + self.rng.gauss(0, sg["noise_std"]))
            generated_ns = now_ns()
            self.charge("send_data")
            self.sent_packets += 1
            self._send({"type": "DATA", "node_id": self.id, "sequence": self.sequence,
                        "config_version": self.config_version, "generated_ns": generated_ns,
                        "value": round(value, 2), "unit": self.cfg["unit"]})
            self._trace("DATA")
            self._post()

    # ------------------------------------------------------------------ polecenia
    def on_command(self, msg: dict):
        """CONFIG: (koszt odbioru) -> duplikat? -> walidacja -> wykonanie -> ACK/ERROR."""
        with self.lock:
            if self.state in ("FAILED", "STOPPED"):
                return                                  # martwy node nie odpowiada
            if self.hook_rng.random() < self.hooks.get("drop_command_prob", 0.0):
                self.stats["test_dropped_commands"] += 1
                return                                  # symulowana strata polecenia
            self.charge("receive_command")              # każdy odebrany datagram kosztuje (także duplikat)
            self.stats["commands_received"] += 1
            cid = msg.get("command_id")
            if cid is None:
                self._post()
                return
            if cid in self.responses:
                # DUPLIKAT: nie wykonujemy ponownie, tylko powtarzamy zapamiętaną odpowiedź
                self.stats["duplicates_ignored"] += 1
                self._send(self.responses[cid], "drop_reply_prob")
                self._trace(f"DUPLICATE {cid}")
                self._post()
                return
            reason = validate_config(msg, self.id, self.config_version, self.state)
            if reason is None:
                self._apply(msg)                        # zmiana dopiero PO pozytywnej walidacji
                self.stats["commands_applied"] += 1
                resp = {"type": "ACK", "command_id": cid, "node_id": self.id, "result": "APPLIED",
                        "config_version": self.config_version, "timestamp_ns": now_ns()}
            else:
                self.stats["commands_rejected"] += 1
                resp = {"type": "ERROR", "command_id": cid, "node_id": self.id, "reason": reason,
                        "current_config_version": self.config_version}
            self.responses[cid] = resp
            self._send(resp, "drop_reply_prob")
            self._trace(f"{resp['type']} {cid}")
            self._post()

    def _apply(self, msg: dict):
        p, v, now = msg["parameter"], msg["value"], now_ns()
        if p == "sample_period_ms":
            self.sample_ms = v
            self.next_sample_ns = min(self.next_sample_ns, now + self.clock.real_ns(v))
        elif p == "status_period_ms":
            self.status_ms = v
            self.next_status_ns = min(self.next_status_ns, now + self.clock.real_ns(v))
        elif p == "operating_state":
            self._set_state(v)
        self.config_version = msg["config_version"]     # wersja rośnie dopiero tutaj

    # ------------------------------------------------------------------ pętle
    def listen(self):
        while not self.stop_event.is_set():
            try:
                data, _ = self.sock.recvfrom(65535)
            except socket.timeout:
                continue
            except OSError:
                break
            msg = decode(data)
            if msg and msg["type"] == "CONFIG":
                self.on_command(msg)

    def run(self):
        os.makedirs(self.cfg["output_dir"], exist_ok=True)
        self.sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        self.sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        self.sock.bind((HOST, self.cfg["port"]))
        self.sock.settimeout(0.05)
        threading.Thread(target=self.listen, daemon=True).start()

        self.clock = SimClock(self.cfg["time_scale"], now_ns())
        self._trace("START")
        with self.lock:
            self._emit_status()                         # pierwszy raport: STARTING
        startup_end = now_ns() + self.clock.real_ns(self.cfg["startup_ms"])
        while not self.stop_event.is_set() and self._t() < self.cfg["duration_s"]:
            now = now_ns()
            with self.lock:
                state = self.state
                if state == "STARTING" and now >= startup_end:
                    self._set_state(self.initial_state)
                    self.next_sample_ns, self.next_status_ns = now, now
            if state in OPERATING_STATES:
                if now >= self.next_sample_ns:
                    self.do_sample()
                    self.next_sample_ns += self.clock.real_ns(self.sample_ms)
                    if self.next_sample_ns < now:       # opóźnienie: bez nadrabiania seriami
                        self.next_sample_ns = now + self.clock.real_ns(self.sample_ms)
                if now >= self.next_status_ns:
                    self.send_status()
                    self.next_status_ns += self.clock.real_ns(self.status_ms)
                    if self.next_status_ns < now:
                        self.next_status_ns = now + self.clock.real_ns(self.status_ms)
            self.stop_event.wait(0.002)
        with self.lock:
            if self.state in OPERATING_STATES:          # normalne zakończenie
                self._set_state("STOPPED")
                self._emit_status()
        self.finish()

    def finish(self):
        with self.lock:
            self._set_state(self.state)                 # domknięcie księgowania czasu w stanie
            self._trace("END")
            out = self.cfg["output_dir"]
            truth = {"node_id": self.id, "final_state": self.state, "final_battery": self.battery_level,
                     "generated": self.sequence, "sent_data": self.sent_packets,
                     "status_sent": self.status_sequence, "config_version": self.config_version,
                     "time_to_critical_s": self.time_to_critical_s, "state_time_s": {
                         k: round(v, 3) for k, v in self.state_time.items()},
                     "mode_changes": self.mode_changes, "mode_change_count": len(self.mode_changes),
                     "time_scale": self.cfg["time_scale"], "commands": self.stats}
            with open(os.path.join(out, f"{self.id}_truth.json"), "w", encoding="utf-8") as f:
                json.dump(truth, f, indent=2, ensure_ascii=False)
            with open(os.path.join(out, f"{self.id}_energy_trace.csv"), "w", newline="",
                      encoding="utf-8") as f:
                w = csv.writer(f)
                w.writerow(["t_sym_s", "battery_level", "state", "sample_period_ms", "event"])
                w.writerows(self.trace)
        self.stop_event.set()
        try:
            self.sock.close()
        except OSError:
            pass


def main():
    p = argparse.ArgumentParser(description="Node WSN (Grupa 1)")
    p.add_argument("--config", required=True)
    p.add_argument("--output-dir", help="nadpisuje output_dir z konfiguracji")
    p.add_argument("--time-scale", type=float, help="nadpisuje time_scale")
    p.add_argument("--duration-s", type=float, help="nadpisuje duration_s (czas symulacji)")
    a = p.parse_args()
    cfg = load_config(a.config, REQUIRED)
    for key, val in (("output_dir", a.output_dir), ("time_scale", a.time_scale),
                     ("duration_s", a.duration_s)):
        if val is not None:
            cfg[key] = val
    Node(cfg).run()


if __name__ == "__main__":
    main()
