"""SINK-MANAGER - odbiera DATA/STATUS/ALERT, utrzymuje tabelę stanu nodów, wysyła CONFIG,
kontroluje ACK/ERROR (timeout + ponowienie tego samego command_id) i prowadzi dziennik.

Uruchomienie:  python sink_manager.py --config config/sink_adaptacyjna.json

Pliki wynikowe (folder `output_dir`):
  management_log.csv  - dziennik zdarzeń zarządczych (kolumny wg polecenia)
  status_log.csv      - każdy odebrany STATUS (do wykresów energii i okresu próbkowania)
  data_log.csv        - każdy odebrany DATA (czas odbioru, flaga duplikatu)
  state_table.csv     - końcowa tabela stanu sinka
  run_meta.json       - start/koniec, time_scale, liczniki ruchu

ZASADY (pułapki, które ten kod pilnuje):
  * Tabela stanu zmienia się WYŁĄCZNIE po komunikatach UDP od nodów (STATUS, ACK, ERROR,
    ALERT, DATA). Wysłanie CONFIG NIE zmienia sample_period_ms ani reported_state w tabeli
    - zmienia tylko `expected_config_version` (zamiar sinka).
  * observed_state = UNREACHABLE to WNIOSEK sinka z braku STATUS (timeout), a FAILED to stan
    raportowany przez node. To dwie różne kolumny i dwie różne rzeczy.
  * Czas reakcji = (odebranie ACK) - (PIERWSZE wysłanie polecenia), oba na zegarze sinka.
  * Duplikat DATA (ten sam node i sequence) nie liczy się jako nowa próbka.
  * ERROR cofa `expected_config_version` do wersji z node'a (polecenie nie zmieniło niczego).
  * Timeout niedostępności = max(status_timeout_ms, 3 * status_period_ms), żeby sink sam nie
    wywoływał fałszywych alarmów po wydłużeniu okresu STATUS.
"""
import argparse
import csv
import json
import os
import socket
import threading
import time

from wsn_common import (HOST, OPERATING_STATES, UNREACHABLE, SimClock, battery_mode,
                        decode, encode, load_config, missing_fields, now_ns)

REQUIRED = {"port": int, "node_ports": dict, "time_scale": (int, float), "duration_s": (int, float),
            "output_dir": str, "status_timeout_ms": int, "command_timeout_ms": int,
            "max_retries": int, "strategy": dict}

LOG_COLUMNS = ["timestamp_ns", "event_type", "node_id", "command_id", "parameter", "old_value",
               "new_value", "config_version", "result", "details"]


class Entry:
    """Jeden wiersz tabeli stanu sinka (pola wg polecenia + pola pomocnicze)."""

    def __init__(self, node_id, default_status_period_ms):
        self.node_id = node_id
        self.observed_state = "UNKNOWN"          # stan obserwowany (może być UNREACHABLE)
        self.reported_state = None               # stan raportowany przez node
        self.last_status_ns = None
        self.battery_level = None
        self.sample_period_ms = None
        self.expected_config_version = None      # zamiar sinka
        self.reported_config_version = None      # to, co zgłosił node
        self.pending_command_id = None
        # pomocnicze
        self.status_period_ms = default_status_period_ms   # znamy je z własnych ACK (STATUS go nie niesie)
        self.last_status_seq = 0
        self.queue = []                          # oczekujące zamiary (parameter, value, powód)
        self.last_intent = None
        self.last_packet = None
        self.mismatch_open = False
        self.mismatch_start = 0
        self.blocked_until_ns = 0                # po ERROR nie ponawiamy od razu decyzji
        self.seen_data = set()


class Manager:
    def __init__(self, cfg: dict, send=None, clock=now_ns, log_dir: str = None):
        self.cfg = cfg
        self.now = clock
        self.start_ns = clock()
        self.sim = SimClock(cfg["time_scale"], self.start_ns)
        self.lock = threading.RLock()
        self._send_override = send
        self.sock = None
        self.strategy = cfg["strategy"]
        self.entries = {nid: Entry(nid, cfg.get("default_status_period_ms", 2000))
                        for nid in cfg["node_ports"]}
        self.commands = {}                       # command_id -> rekord polecenia
        self.cmd_counter = 0
        self.scenario = sorted(cfg.get("scenario", []), key=lambda a: a["at_s"])
        self.counts = {"sent": {}, "received": {}, "malformed": 0, "unknown_node": 0}
        self.done = False
        self.started = True            # w run(): zegar eksperymentu startuje od pierwszego komunikatu
        self.last_print = 0
        out = log_dir or cfg["output_dir"]
        os.makedirs(out, exist_ok=True)
        self.out = out
        self._files = {}
        self._writers = {}
        self._open("management_log.csv", LOG_COLUMNS)
        self._open("status_log.csv", ["timestamp_ns", "node_id", "status_sequence", "operating_state",
                                      "battery_level", "sample_period_ms", "config_version",
                                      "sent_packets", "observed_state"])
        self._open("data_log.csv", ["timestamp_ns", "node_id", "sequence", "generated_ns",
                                    "config_version", "value", "duplicate"])

    # ------------------------------------------------------------------ logi
    def _open(self, name, header):
        f = open(os.path.join(self.out, name), "w", newline="", encoding="utf-8")
        self._files[name] = f
        self._writers[name] = csv.writer(f)
        self._writers[name].writerow(header)

    def _log(self, ts, event, node="", cid="", param="", old="", new="", ver="", result="", details=""):
        self._writers["management_log.csv"].writerow([ts, event, node, cid, param, old, new, ver,
                                                      result, details])

    def _count(self, kind, mtype):
        self.counts[kind][mtype] = self.counts[kind].get(mtype, 0) + 1

    # ------------------------------------------------------------------ wysyłanie
    def _send(self, node_id: str, msg: dict):
        self._count("sent", msg["type"])
        if self._send_override:
            self._send_override(node_id, msg)
        elif self.sock:
            try:
                self.sock.sendto(encode(msg), (HOST, self.cfg["node_ports"][node_id]))
            except OSError:
                pass

    def send_config(self, e: Entry, parameter, value, now, reason=""):
        """Nowe polecenie CONFIG z unikatowym command_id i wersją = reported + 1."""
        self.cmd_counter += 1
        cid = f"cmd_{self.cmd_counter:03d}"
        version = e.reported_config_version + 1
        old = e.reported_state if parameter == "operating_state" else (
            e.sample_period_ms if parameter == "sample_period_ms" else e.status_period_ms)
        pkt = {"type": "CONFIG", "command_id": cid, "destination": e.node_id, "parameter": parameter,
               "value": value, "config_version": version, "sent_ns": now}
        self.commands[cid] = {"node": e.node_id, "parameter": parameter, "value": value,
                              "version": version, "first_sent_ns": now, "last_sent_ns": now,
                              "tries": 1, "state": "PENDING", "packet": pkt}
        e.pending_command_id = cid
        e.expected_config_version = version       # zamiar; tabela (okres, stan) NIE jest ruszana
        e.last_intent = (parameter, value)
        e.last_packet = pkt
        self._log(now, "COMMAND_SENT", e.node_id, cid, parameter, old, value, version, "",
                  f"reason={reason}" if reason else "")
        self._send(e.node_id, pkt)
        self._check_config(e, now)

    def pump(self, e: Entry, now):
        """Wysyła następny zamiar z kolejki, jeśli nic nie czeka na ACK (max 1 polecenie na node)."""
        if e.pending_command_id is None and e.queue and e.reported_config_version is not None:
            parameter, value, reason = e.queue.pop(0)
            self.send_config(e, parameter, value, now, reason)

    # ------------------------------------------------------------------ odbiór
    def process(self, msg: dict, rx_ns: int):
        """Obsługa jednego odebranego komunikatu (rx_ns = czas odbioru na zegarze sinka)."""
        with self.lock:
            t = msg.get("type")
            if t not in ("DATA", "STATUS", "ACK", "ERROR", "ALERT") or missing_fields(msg):
                self.counts["malformed"] += 1
                return
            e = self.entries.get(msg["node_id"])
            if e is None:
                self.counts["unknown_node"] += 1
                return
            self._count("received", t)
            {"DATA": self.on_data, "STATUS": self.on_status, "ACK": self.on_ack,
             "ERROR": self.on_error, "ALERT": self.on_alert}[t](e, msg, rx_ns)

    def on_data(self, e, m, now):
        dup = m["sequence"] in e.seen_data
        e.seen_data.add(m["sequence"])
        self._writers["data_log.csv"].writerow([now, e.node_id, m["sequence"], m["generated_ns"],
                                                m["config_version"], m["value"], int(dup)])
        if dup:
            return                                # duplikat nie jest nową próbką
        if e.reported_config_version is None or m["config_version"] > e.reported_config_version:
            e.reported_config_version = m["config_version"]
        self._check_config(e, now)

    def on_status(self, e, m, now):
        stale = m["status_sequence"] <= e.last_status_seq
        self._log(now, "STATUS_RECEIVED", e.node_id, "", "operating_state", "", m["operating_state"],
                  m["config_version"], "", f"battery={m['battery_level']};period={m['sample_period_ms']};"
                  f"seq={m['status_sequence']}" + (";stale_or_duplicate" if stale else ""))
        if stale:
            return                                # stary lub zdublowany STATUS nie rusza tabeli
        self._writers["status_log.csv"].writerow([
            now, e.node_id, m["status_sequence"], m["operating_state"], m["battery_level"],
            m["sample_period_ms"], m["config_version"], m["sent_packets"], e.observed_state])
        e.last_status_seq = m["status_sequence"]
        if e.observed_state == UNREACHABLE:
            self._log(now, "NODE_REACHABLE", e.node_id, details="STATUS po przerwie")
        e.last_status_ns = now
        e.reported_state = m["operating_state"]
        e.observed_state = m["operating_state"]
        e.battery_level = m["battery_level"]
        e.sample_period_ms = m["sample_period_ms"]
        e.reported_config_version = m["config_version"]
        if e.expected_config_version is None:
            e.expected_config_version = m["config_version"]    # wersja bazowa przy pierwszym STATUS
        self._check_config(e, now)
        self.pump(e, now)
        self.decide(e, now)

    def on_alert(self, e, m, now):
        self._log(now, "ALERT_RECEIVED", e.node_id, "", m["alert_type"], "", m["value"], "", "",
                  f"threshold={m['threshold']}")
        e.battery_level = m["value"]              # ALERT niesie świeższy poziom baterii
        self.decide(e, now)

    def on_ack(self, e, m, now):
        rec = self.commands.get(m["command_id"])
        if rec is None or rec["node"] != e.node_id:
            self._log(now, "ACK_RECEIVED", e.node_id, m["command_id"], "", "", "", m["config_version"],
                      m["result"], "unknown_command")
            return
        if rec["state"] == "ACKED":
            self._log(now, "ACK_RECEIVED", e.node_id, m["command_id"], rec["parameter"], "", rec["value"],
                      m["config_version"], m["result"], "duplicate_ack")
            return
        late = rec["state"] == "GAVE_UP"
        resp_ms = self.sim.sim_ms(now - rec["first_sent_ns"])
        self._log(now, "ACK_RECEIVED", e.node_id, m["command_id"], rec["parameter"], "", rec["value"],
                  m["config_version"], m["result"], f"response_ms={resp_ms:.1f}" + (";late_ack" if late else ""))
        rec["state"] = "ACKED"
        rec["ack_ns"] = now
        if e.pending_command_id == m["command_id"]:
            e.pending_command_id = None
        # ACK to komunikat UDP od noda - wolno na jego podstawie zaktualizować tabelę
        p, v = rec["parameter"], rec["value"]
        if p == "sample_period_ms":
            e.sample_period_ms = v
        elif p == "operating_state":
            e.reported_state = v
            if e.observed_state != UNREACHABLE:        # UNREACHABLE zmienia dopiero STATUS
                e.observed_state = v
        elif p == "status_period_ms":
            e.status_period_ms = v
        e.reported_config_version = m["config_version"]
        self._check_config(e, now)
        self.pump(e, now)
        self.decide(e, now)

    def on_error(self, e, m, now):
        rec = self.commands.get(m["command_id"])
        if rec is None:
            note = "unknown_command"
        elif rec["state"] in ("ACKED", "ERROR"):
            note = "duplicate_error"                  # powtórzona odpowiedź na duplikat polecenia
        else:
            note = f"response_ms={self.sim.sim_ms(now - rec['first_sent_ns']):.1f}"
        self._log(now, "ERROR_RECEIVED", e.node_id, m["command_id"], rec["parameter"] if rec else "",
                  "", rec["value"] if rec else "", m["current_config_version"], m["reason"], note)
        if rec is None or rec["state"] in ("ACKED", "ERROR"):
            return
        rec["state"] = "ERROR"
        rec["ack_ns"] = now
        if e.pending_command_id == m["command_id"]:
            e.pending_command_id = None
        # polecenie nic nie zmieniło: wersja oczekiwana wraca do wersji zgłoszonej przez node
        e.reported_config_version = m["current_config_version"]
        e.expected_config_version = m["current_config_version"]
        e.last_intent = None
        e.queue.clear()
        e.blocked_until_ns = now + self.sim.real_ns(5000)       # 5 s symulacji bez nowych decyzji
        self._check_config(e, now, cause="rollback_after_error")
        self.pump(e, now)

    # ------------------------------------------------------------------ spójność konfiguracji
    def _check_config(self, e: Entry, now, cause=None):
        """expected != reported => okres niespójności (CONFIG_MISMATCH ... CONFIG_RESTORED)."""
        if e.expected_config_version is None or e.reported_config_version is None:
            return
        if e.pending_command_id is None and e.reported_config_version > e.expected_config_version:
            e.expected_config_version = e.reported_config_version   # node jest "do przodu": przyjmujemy
            cause = cause or "reported_ahead_adopted"
        mismatch = e.expected_config_version != e.reported_config_version
        if mismatch and not e.mismatch_open:
            e.mismatch_open, e.mismatch_start = True, now
            why = "command_in_flight" if e.pending_command_id else "unexplained_status_report"
            self._log(now, "CONFIG_MISMATCH", e.node_id, e.pending_command_id or "", "config_version",
                      e.reported_config_version, e.expected_config_version, e.reported_config_version, "",
                      f"cause={why}")
        elif not mismatch and e.mismatch_open:
            e.mismatch_open = False
            self._log(now, "CONFIG_RESTORED", e.node_id, "", "config_version", "",
                      e.reported_config_version, e.reported_config_version, "",
                      f"cause={cause or 'ack_received'};duration_ms="
                      f"{self.sim.sim_ms(now - e.mismatch_start):.1f}")
        # niespójność bez żadnego polecenia w locie => odtwórz ostatni zamiar
        if (mismatch and e.pending_command_id is None and not e.queue and e.last_intent
                and e.reported_config_version < e.expected_config_version):
            p, v = e.last_intent
            e.queue.append((p, v, "restore_config"))
            self._log(now, "RESTORE_SCHEDULED", e.node_id, "", p, "", v, "", "",
                      "niespójność bez polecenia w locie")

    # ------------------------------------------------------------------ strategia adaptacyjna
    def decide(self, e: Entry, now):
        """Decyzja zarządcza na podstawie OBSERWOWANEGO poziomu baterii (nie wiedzy z konfiguracji)."""
        st = self.strategy
        if st.get("mode") != "adaptive":
            return
        if (e.pending_command_id or e.queue or now < e.blocked_until_ns or e.battery_level is None
                or e.reported_state not in OPERATING_STATES or e.observed_state == UNREACHABLE):
            return
        ov = st.get("node_overrides", {}).get(e.node_id, {})       # np. wyższy priorytet noda
        mode = battery_mode(e.battery_level, ov.get("degraded_below", st["degraded_below"]),
                            ov.get("sleep_below", st["sleep_below"]))
        period = st["periods_ms"][mode]
        intents = []
        if e.reported_state != mode:
            intents.append(("operating_state", mode, "battery"))
        if e.sample_period_ms != period:
            intents.append(("sample_period_ms", period, "battery"))
        sp = st.get("sleep_status_period_ms")
        if mode == "SLEEP" and sp and e.status_period_ms != sp:
            intents.append(("status_period_ms", sp, "battery"))
        if intents:
            self._log(now, "STRATEGY_DECISION", e.node_id, "", "operating_state", e.reported_state, mode,
                      e.reported_config_version, "", f"battery={e.battery_level}")
            e.queue.extend(intents)
            self.pump(e, now)

    # ------------------------------------------------------------------ zegar
    def tick(self, now):
        with self.lock:
            if not self.started:
                if now - self.start_ns > self.sim.real_ns(30000):   # nikt się nie odezwał
                    self.done = True
                return
            for e in self.entries.values():
                # 1) niedostępność: brak STATUS dłużej niż timeout (stan obserwowany)
                if e.last_status_ns is not None and e.observed_state not in (UNREACHABLE, "STOPPED"):
                    timeout_ms = max(self.cfg["status_timeout_ms"], 3 * e.status_period_ms)
                    silence = now - e.last_status_ns
                    if silence > self.sim.real_ns(timeout_ms):
                        e.observed_state = UNREACHABLE
                        self._log(now, "NODE_UNREACHABLE", e.node_id, "", "observed_state",
                                  e.reported_state, UNREACHABLE, e.reported_config_version, "",
                                  f"silence_ms={self.sim.sim_ms(silence):.0f};reported_state={e.reported_state}")
                # 2) timeout polecenia: ponowienie TEGO SAMEGO command_id (węzeł zdeduplikuje)
                cid = e.pending_command_id
                if cid:
                    rec = self.commands[cid]
                    if now - rec["last_sent_ns"] >= self.sim.real_ns(self.cfg["command_timeout_ms"]):
                        if rec["tries"] <= self.cfg["max_retries"]:
                            self._log(now, "COMMAND_TIMEOUT", e.node_id, cid, rec["parameter"], "",
                                      rec["value"], rec["version"], "", f"attempt={rec['tries']}")
                            rec["tries"] += 1
                            rec["last_sent_ns"] = now
                            self._log(now, "COMMAND_SENT", e.node_id, cid, rec["parameter"], "",
                                      rec["value"], rec["version"], "", f"retry={rec['tries'] - 1}")
                            self._send(e.node_id, rec["packet"])
                        else:
                            self._log(now, "COMMAND_TIMEOUT", e.node_id, cid, rec["parameter"], "",
                                      rec["value"], rec["version"], "GAVE_UP", "max_retries")
                            rec["state"] = "GAVE_UP"
                            e.pending_command_id = None
                            self.pump(e, now)
            # 3) scenariusz poleceń (czas symulacji)
            t = self.sim.sim_s(now)
            while self.scenario and self.scenario[0]["at_s"] <= t:
                self.run_scenario_action(self.scenario.pop(0), now)
            if t >= self.cfg["duration_s"] + self.cfg.get("grace_s", 3):
                self.done = True            # grace_s: czas na ostatnie STATUS (STOPPED) i DATA

    def run_scenario_action(self, a, now):
        e = self.entries.get(a["node"])
        if e is None:
            return
        if a.get("action") == "RESEND_LAST":
            # test duplikatu: ten sam datagram, ten sam command_id
            if e.last_packet:
                self._log(now, "COMMAND_SENT", e.node_id, e.last_packet["command_id"],
                          e.last_packet["parameter"], "", e.last_packet["value"],
                          e.last_packet["config_version"], "", "duplicate_test_resend")
                self._send(e.node_id, e.last_packet)
        else:
            e.queue.append((a["parameter"], a["value"], "scenario"))
            self.pump(e, now)

    # ------------------------------------------------------------------ tabela / koniec
    def render_table(self) -> str:
        head = (f"{'node_id':8}|{'observed':12}|{'reported':9}|{'battery':8}|{'period':7}|"
                f"{'exp_v':6}|{'rep_v':6}|pending")
        rows = [head, "-" * len(head)]
        for e in self.entries.values():
            rows.append(f"{e.node_id:8}|{e.observed_state:12}|{str(e.reported_state):9}|"
                        f"{str(e.battery_level):8}|{str(e.sample_period_ms):7}|"
                        f"{str(e.expected_config_version):6}|{str(e.reported_config_version):6}|"
                        f"{e.pending_command_id or '-'}")
        return "\n".join(rows)

    def finish(self):
        with self.lock:
            end = self.now()
            for e in self.entries.values():          # domknij otwarte okresy niespójności
                if e.mismatch_open:
                    self._log(end, "MISMATCH_OPEN_AT_END", e.node_id, details=
                              f"duration_ms={self.sim.sim_ms(end - e.mismatch_start):.1f}")
            with open(os.path.join(self.out, "state_table.csv"), "w", newline="", encoding="utf-8") as f:
                w = csv.writer(f)
                w.writerow(["node_id", "observed_state", "reported_state", "last_status_ns", "battery_level",
                            "sample_period_ms", "expected_config_version", "reported_config_version",
                            "pending_command_id"])
                for e in self.entries.values():
                    w.writerow([e.node_id, e.observed_state, e.reported_state, e.last_status_ns,
                                e.battery_level, e.sample_period_ms, e.expected_config_version,
                                e.reported_config_version, e.pending_command_id or ""])
            with open(os.path.join(self.out, "run_meta.json"), "w", encoding="utf-8") as f:
                json.dump({"start_ns": self.start_ns, "end_ns": end, "time_scale": self.cfg["time_scale"],
                           "duration_s": self.cfg["duration_s"], "strategy": self.strategy.get("mode"),
                           "nodes": list(self.entries), "counts": self.counts,
                           "status_timeout_ms": self.cfg["status_timeout_ms"]}, f, indent=2)
            self.close_logs()

    def close_logs(self):
        for f in self._files.values():
            if not f.closed:
                f.close()

    # ------------------------------------------------------------------ główna pętla
    def run(self):
        self.sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        self.sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        self.sock.bind((HOST, self.cfg["port"]))
        self.sock.settimeout(0.02)
        self.start_ns = now_ns()                       # tymczasowo; po 1. komunikacie nadpisane
        self.sim = SimClock(self.cfg["time_scale"], self.start_ns)
        self.started = False
        every = self.cfg.get("table_print_s", 0)
        while not self.done:
            try:
                data, _ = self.sock.recvfrom(65535)
                rx = now_ns()                          # czas odbioru zapisujemy NATYCHMIAST
                msg = decode(data)
                if not self.started and msg is not None:
                    self.started = True                # t = 0 eksperymentu = pierwszy odebrany komunikat
                    self.start_ns = rx
                    self.sim = SimClock(self.cfg["time_scale"], rx)
                if msg is None:
                    self.counts["malformed"] += 1
                else:
                    self.process(msg, rx)
            except socket.timeout:
                pass
            self.tick(now_ns())
            if every and time.time() - self.last_print > every:
                self.last_print = time.time()
                print(f"\n[t_sym={self.sim.sim_s(now_ns()):6.1f}s]\n{self.render_table()}", flush=True)
        self.finish()
        self.sock.close()


def main():
    p = argparse.ArgumentParser(description="Sink-manager WSN (Grupa 1)")
    p.add_argument("--config", required=True)
    p.add_argument("--output-dir")
    p.add_argument("--time-scale", type=float)
    p.add_argument("--duration-s", type=float)
    a = p.parse_args()
    cfg = load_config(a.config, REQUIRED)
    for key, val in (("output_dir", a.output_dir), ("time_scale", a.time_scale),
                     ("duration_s", a.duration_s)):
        if val is not None:
            cfg[key] = val
    Manager(cfg).run()


if __name__ == "__main__":
    main()
