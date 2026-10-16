"""Testy laboratorium WSN (Grupa 1).   Uruchomienie:  .venv/bin/python -m unittest -v test_wsn

Testy jednostkowe działają bez sieci (wstrzyknięte funkcje wysyłania i fałszywy zegar).
Jeden test integracyjny uruchamia prawdziwe procesy (UDP, porty 6000 i 6101-6103 muszą być wolne).
"""
import csv
import json
import os
import shutil
import sys
import tempfile
import unittest

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))   # działa z dowolnego katalogu roboczego

import analyze
import wsn_common as wc
from node import Node
from sink_manager import Manager

def read_csv(path):
    with open(path, encoding="utf-8") as f:       # zawsze zamykamy plik
        return list(csv.DictReader(f))


def read_json(path):
    with open(path, encoding="utf-8") as f:
        return json.load(f)


SEC = 1_000_000_000          # fałszywy zegar: 1 s = 1e9 ns (time_scale = 1)


def node_cfg(**over):
    cfg = {"node_id": "node_1", "port": 6101, "sink_port": 6000, "time_scale": 1, "duration_s": 100,
           "seed": 1, "output_dir": tempfile.gettempdir(), "sample_period_ms": 500,
           "status_period_ms": 2000, "startup_ms": 1000, "unit": "degC",
           "signal": {"base": 20, "amplitude": 1, "period_s": 60, "noise_std": 0.1},
           "energy": {"initial": 100.0, "generate": 0.10, "send_data": 0.50, "send_status": 0.25,
                      "receive_command": 0.10, "sleep_cycle": 0.01, "low_battery_threshold": 20.0}}
    cfg.update(over)
    return cfg


def make_node(**over):
    sent = []
    n = Node(node_cfg(**over), send=sent.append)
    n.state = "ACTIVE"                         # pomijamy fazę STARTING
    return n, sent


def config(cid, param, value, version, dest="node_1"):
    return {"type": "CONFIG", "command_id": cid, "destination": dest, "parameter": param,
            "value": value, "config_version": version, "sent_ns": 1}


# --------------------------------------------------------------------------
class TestWalidacjaPolecenia(unittest.TestCase):
    def check(self, msg, expected, version=1, state="ACTIVE"):
        self.assertEqual(wc.validate_config(msg, "node_1", version, state), expected)

    def test_poprawne(self):
        self.check(config("c", "sample_period_ms", 1000, 2), None)
        self.check(config("c", "operating_state", "SLEEP", 2), None)
        self.check(config("c", "status_period_ms", 4000, 2), None)

    def test_granice_zakresu(self):
        for v, exp in ((99, "VALUE_OUT_OF_RANGE"), (100, None), (5000, None), (5001, "VALUE_OUT_OF_RANGE"),
                       (0, "VALUE_OUT_OF_RANGE"), (-5, "VALUE_OUT_OF_RANGE")):
            self.check(config("c", "sample_period_ms", v, 2), exp)

    def test_bool_nie_jest_poprawna_liczba(self):
        # pułapka: isinstance(True, int) == True, a True == 1 ... ale 1 i tak byłoby poza zakresem
        self.check(config("c", "sample_period_ms", True, 2), "INVALID_VALUE_TYPE")
        self.check(config("c", "sample_period_ms", False, 2), "INVALID_VALUE_TYPE")

    def test_zly_typ(self):
        self.check(config("c", "sample_period_ms", "500", 2), "INVALID_VALUE_TYPE")
        self.check(config("c", "sample_period_ms", 500.0, 2), "INVALID_VALUE_TYPE")
        self.check(config("c", "sample_period_ms", None, 2), "INVALID_VALUE_TYPE")

    def test_nieznany_parametr_i_zly_stan(self):
        self.check(config("c", "battery_level", 100, 2), "UNKNOWN_PARAMETER")
        self.check(config("c", "operating_state", "FAILED", 2), "INVALID_STATE_VALUE")   # nie można "ustawić" FAILED
        self.check(config("c", "operating_state", "sleep", 2), "INVALID_STATE_VALUE")    # wielkość liter

    def test_zly_adresat_i_brakujace_pola(self):
        self.check(config("c", "sample_period_ms", 500, 2, dest="node_2"), "WRONG_DESTINATION")
        bad = config("c", "sample_period_ms", 500, 2)
        del bad["value"]
        self.check(bad, "MALFORMED_COMMAND")

    def test_wersja_konfiguracji(self):
        self.check(config("c", "sample_period_ms", 500, 1), "STALE_CONFIG_VERSION")      # == bieżąca
        self.check(config("c", "sample_period_ms", 500, 0), "STALE_CONFIG_VERSION")
        self.check(config("c", "sample_period_ms", 500, "2"), "STALE_CONFIG_VERSION")

    def test_stan_noda(self):
        self.check(config("c", "sample_period_ms", 500, 2), "NODE_NOT_READY", state="STARTING")
        self.check(config("c", "sample_period_ms", 500, 2), "NODE_NOT_OPERATIONAL", state="FAILED")

    def test_decode_nie_wywala_sie_na_smieciach(self):
        for raw in (b"", b"\xff\xfe", b"{", b"[1,2]", b'{"x":1}', b'{"type":5}'):
            self.assertIsNone(wc.decode(raw))


class TestEnergia(unittest.TestCase):
    def test_progi_wlacznie_i_wylacznie(self):
        self.assertEqual(wc.battery_mode(100.0), "ACTIVE")
        self.assertEqual(wc.battery_mode(50.001), "ACTIVE")
        self.assertEqual(wc.battery_mode(50.0), "DEGRADED")        # 50 NIE jest > 50
        self.assertEqual(wc.battery_mode(20.001), "DEGRADED")
        self.assertEqual(wc.battery_mode(20.0), "SLEEP")           # 20 jest <= 20
        self.assertEqual(wc.battery_mode(0.0), "SLEEP")

    def test_arytmetyka_calkowita_zamiast_float(self):
        n, _ = make_node()
        for _ in range(500):                                       # 500 x 0.10 = 50.0 dokładnie
            n.charge("generate")
        self.assertEqual(n.battery_units, 50000)
        self.assertEqual(wc.battery_mode(n.battery_level), "DEGRADED")
        # na floatach 100 - 0.1*500 nie musi dać równo 50.0
        f = 100.0
        for _ in range(500):
            f -= 0.1
        self.assertNotEqual(f, 50.0)

    def test_koszty_z_polecenia(self):
        n, _ = make_node()
        n.charge("generate"); n.charge("send_data"); n.charge("send_status")
        n.charge("receive_command"); n.charge("sleep_cycle")
        self.assertAlmostEqual(n.battery_level, 100 - (0.10 + 0.50 + 0.25 + 0.10 + 0.01), places=6)

    def test_alert_low_battery_tylko_raz(self):
        n, sent = make_node()
        n.battery_units = wc.to_units(20.2)
        for _ in range(10):
            n.do_sample()
        alerts = [m for m in sent if m["type"] == "ALERT"]
        self.assertEqual(len(alerts), 1)
        self.assertEqual(alerts[0]["alert_type"], "LOW_BATTERY")
        self.assertLessEqual(alerts[0]["value"], alerts[0]["threshold"])

    def test_wyczerpanie_to_failed_i_cisza(self):
        n, sent = make_node()
        n.battery_units = 700                                      # 0.7: starczy na jeden pomiar
        n.do_sample()
        n.do_sample()
        self.assertEqual(n.state, "FAILED")
        statuses = [m for m in sent if m["type"] == "STATUS"]
        self.assertEqual([s["operating_state"] for s in statuses], ["FAILED"])   # jeden ostatni raport
        count = len(sent)
        n.do_sample(); n.send_status()
        self.assertEqual(len(sent), count)                         # po awarii node milczy
        n.on_command(config("c", "sample_period_ms", 700, 2))
        self.assertEqual(len(sent), count)                         # i nie odpowiada na polecenia


class TestNodePolecenia(unittest.TestCase):
    def test_poprawne_polecenie_ack_i_wersja(self):
        n, sent = make_node()
        n.on_command(config("cmd_1", "sample_period_ms", 1000, 2))
        ack = sent[-1]
        self.assertEqual((ack["type"], ack["result"], ack["config_version"]), ("ACK", "APPLIED", 2))
        self.assertEqual((n.sample_ms, n.config_version), (1000, 2))

    def test_niepoprawne_polecenie_error_bez_zmiany(self):
        n, sent = make_node()
        before = (n.sample_ms, n.config_version, n.state)
        n.on_command(config("cmd_1", "sample_period_ms", 50, 2))
        err = sent[-1]
        self.assertEqual((err["type"], err["reason"], err["current_config_version"]),
                         ("ERROR", "VALUE_OUT_OF_RANGE", 1))
        self.assertEqual((n.sample_ms, n.config_version, n.state), before)    # nic nie zmienione

    def test_duplikat_nie_jest_wykonany_ponownie(self):
        n, sent = make_node()
        msg = config("cmd_1", "sample_period_ms", 1000, 2)
        n.on_command(msg)
        n.sample_ms = 777                                    # "ktoś" zmienił okres - duplikat nie może tego cofnąć
        n.on_command(dict(msg))                              # ten sam command_id
        self.assertEqual(n.sample_ms, 777)
        self.assertEqual(n.config_version, 2)                # wersja NIE urosła do 3
        self.assertEqual(n.stats["commands_applied"], 1)
        self.assertEqual(n.stats["duplicates_ignored"], 1)
        self.assertEqual(sent[-1], sent[-2])                 # odesłano tę samą odpowiedź
        self.assertAlmostEqual(n.battery_level, 100 - 2 * 0.10, places=6)    # ale odbiór kosztował 2 x

    def test_duplikat_odrzuconego_polecenia_tez_nie_przechodzi(self):
        n, sent = make_node()
        n.on_command(config("c", "sample_period_ms", 50, 2))
        n.on_command(config("c", "sample_period_ms", 50, 2))
        self.assertEqual([m["type"] for m in sent], ["ERROR", "ERROR"])
        self.assertEqual(n.stats["commands_rejected"], 1)

    def test_zmiana_stanu_pracy(self):
        n, sent = make_node()
        n.on_command(config("c1", "operating_state", "DEGRADED", 2))
        n.on_command(config("c2", "operating_state", "SLEEP", 3))
        self.assertEqual(n.state, "SLEEP")
        self.assertEqual(n.mode_changes[-1]["to"], "SLEEP")
        self.assertEqual(n.config_version, 3)

    def test_data_i_status_niosa_aktualna_wersje(self):
        n, sent = make_node()
        n.do_sample()
        n.on_command(config("c", "sample_period_ms", 1000, 2))
        n.do_sample()
        n.send_status()
        data = [m for m in sent if m["type"] == "DATA"]
        status = [m for m in sent if m["type"] == "STATUS"][-1]
        self.assertEqual([d["config_version"] for d in data], [1, 2])
        self.assertEqual((status["config_version"], status["sample_period_ms"]), (2, 1000))
        self.assertEqual([d["sequence"] for d in data], [1, 2])

    def test_polecenie_w_starting_odrzucone(self):
        n, sent = make_node()
        n.state = "STARTING"
        n.on_command(config("c", "sample_period_ms", 1000, 2))
        self.assertEqual(sent[-1]["reason"], "NODE_NOT_READY")

    def test_sleep_wariant_b_cykl_zastepuje_koszt_pomiaru(self):
        cfg = node_cfg()
        cfg["energy"]["sleep_mode"] = "replace"
        sent = []
        n = Node(cfg, send=sent.append)
        n.state = "SLEEP"
        n.do_sample()
        self.assertAlmostEqual(100 - n.battery_level, 0.01, places=6)

    def test_sleep_dolicza_koszt_cyklu(self):
        n, _ = make_node()
        n.state = "SLEEP"
        n.do_sample()
        self.assertAlmostEqual(100 - n.battery_level, 0.10 + 0.01 + 0.50, places=6)


# --------------------------------------------------------------------------
class FakeClock:
    t = 0

    def __call__(self):
        return self.t

    def advance(self, seconds):
        self.t += int(seconds * SEC)


_MANAGERS = []                                   # do sprzątania po testach (pliki logów)


def make_manager(mode="none", **over):
    cfg = {"port": 6000, "node_ports": {"node_1": 6101, "node_2": 6102}, "time_scale": 1,
           "duration_s": 1000, "output_dir": "x", "status_timeout_ms": 6000, "command_timeout_ms": 1000,
           "max_retries": 3, "default_status_period_ms": 2000,
           "strategy": {"mode": mode, "degraded_below": 50.0, "sleep_below": 20.0,
                        "periods_ms": {"ACTIVE": 500, "DEGRADED": 1000, "SLEEP": 3000}}}
    cfg.update(over)
    clock, sent, tmp = FakeClock(), [], tempfile.mkdtemp()
    m = Manager(cfg, send=lambda node, msg: sent.append((node, msg)), clock=clock, log_dir=tmp)
    m.tmp = tmp
    _MANAGERS.append(m)
    return m, clock, sent


def status(seq, state="ACTIVE", battery=90.0, period=500, version=1, node="node_1"):
    return {"type": "STATUS", "node_id": node, "status_sequence": seq, "timestamp_ns": 5,
            "operating_state": state, "battery_level": battery, "sample_period_ms": period,
            "sent_packets": 3, "config_version": version}


def ack(cid, version, node="node_1"):
    return {"type": "ACK", "command_id": cid, "node_id": node, "result": "APPLIED",
            "config_version": version, "timestamp_ns": 123456789}


class TestSinkManager(unittest.TestCase):
    def tearDown(self):
        while _MANAGERS:
            m = _MANAGERS.pop()
            m.close_logs()
            shutil.rmtree(m.tmp, ignore_errors=True)

    def events(self, m):
        m._files["management_log.csv"].flush()
        return read_csv(os.path.join(m.tmp, "management_log.csv"))

    def test_tabela_aktualizowana_tylko_komunikatami(self):
        m, clock, sent = make_manager()
        m.process(status(1), clock())
        e = m.entries["node_1"]
        m.entries["node_1"].queue.append(("sample_period_ms", 1000, "test"))
        m.pump(e, clock())
        # CONFIG wysłany, ale tabela NIE może jeszcze pokazywać nowego okresu
        self.assertEqual(sent[-1][1]["type"], "CONFIG")
        self.assertEqual(e.sample_period_ms, 500)
        self.assertEqual(e.expected_config_version, 2)
        self.assertEqual(e.reported_config_version, 1)
        self.assertEqual(e.pending_command_id, "cmd_001")
        m.process(ack("cmd_001", 2), clock())
        self.assertEqual(e.sample_period_ms, 1000)
        self.assertEqual((e.expected_config_version, e.reported_config_version), (2, 2))
        self.assertIsNone(e.pending_command_id)

    def test_czas_reakcji_z_zegara_sinka_nie_z_pola_noda(self):
        m, clock, sent = make_manager()
        m.process(status(1), clock())
        e = m.entries["node_1"]
        e.queue.append(("sample_period_ms", 1000, "t")); m.pump(e, clock())
        clock.advance(0.25)
        m.process(ack("cmd_001", 2), clock())      # timestamp_ns w ACK jest absurdalny - ma być ignorowany
        met = analyze.command_metrics(self.events(m))
        self.assertAlmostEqual(met["response_ms_mean"], 250.0, places=3)      # ms RZECZYWISTE (bez time_scale)
        self.assertEqual(met["success_rate"], 1.0)

    def test_error_cofa_wersje_oczekiwana(self):
        m, clock, sent = make_manager()
        m.process(status(1), clock())
        e = m.entries["node_1"]
        e.queue.append(("sample_period_ms", 50, "t")); m.pump(e, clock())
        self.assertEqual(e.expected_config_version, 2)
        m.process({"type": "ERROR", "command_id": "cmd_001", "node_id": "node_1",
                   "reason": "VALUE_OUT_OF_RANGE", "current_config_version": 1}, clock())
        self.assertEqual((e.expected_config_version, e.reported_config_version), (1, 1))
        self.assertEqual(e.sample_period_ms, 500)              # tabela bez zmian
        self.assertFalse(e.mismatch_open)
        self.assertEqual(len([s for s in sent if s[1]["type"] == "CONFIG"]), 1)   # bez pętli ponowień

    def test_niedostepnosc_po_6_s_to_nie_failed(self):
        m, clock, sent = make_manager()
        m.process(status(1, "ACTIVE"), clock())
        clock.advance(5.9); m.tick(clock())
        self.assertEqual(m.entries["node_1"].observed_state, "ACTIVE")
        clock.advance(0.3); m.tick(clock())
        e = m.entries["node_1"]
        self.assertEqual(e.observed_state, wc.UNREACHABLE)
        self.assertEqual(e.reported_state, "ACTIVE")          # raportowany stan NIE jest nadpisywany
        m.process(status(2, "ACTIVE"), clock())               # po powrocie raportów wraca stan
        self.assertEqual(e.observed_state, "ACTIVE")
        self.assertIn("NODE_REACHABLE", [r["event_type"] for r in self.events(m)])

    def test_failed_raportowany_a_potem_unreachable(self):
        m, clock, sent = make_manager()
        m.process(status(1, "ACTIVE"), clock())
        m.process(status(2, "FAILED", battery=0.0), clock())
        e = m.entries["node_1"]
        self.assertEqual((e.reported_state, e.observed_state), ("FAILED", "FAILED"))
        clock.advance(7); m.tick(clock())
        self.assertEqual((e.reported_state, e.observed_state), ("FAILED", wc.UNREACHABLE))

    def test_stopped_nie_jest_niedostepny(self):
        m, clock, sent = make_manager()
        m.process(status(1, "STOPPED"), clock())
        clock.advance(60); m.tick(clock())
        self.assertEqual(m.entries["node_1"].observed_state, "STOPPED")

    def test_timeout_dostosowany_do_okresu_status(self):
        m, clock, sent = make_manager()
        m.process(status(1), clock())
        e = m.entries["node_1"]
        e.queue.append(("status_period_ms", 10000, "t")); m.pump(e, clock())
        m.process(ack("cmd_001", 2), clock())
        self.assertEqual(e.status_period_ms, 10000)
        clock.advance(20); m.tick(clock())                    # 20 s < 3 x 10 s: nie ma fałszywego alarmu
        self.assertEqual(e.observed_state, "ACTIVE")
        clock.advance(11); m.tick(clock())
        self.assertEqual(e.observed_state, wc.UNREACHABLE)

    def test_stary_i_zdublowany_status_ignorowany(self):
        m, clock, sent = make_manager()
        m.process(status(5, battery=80.0), clock())
        m.process(status(4, battery=99.0), clock())            # starszy
        m.process(status(5, battery=99.0), clock())            # zdublowany numer
        self.assertEqual(m.entries["node_1"].battery_level, 80.0)

    def test_duplikat_data_to_nie_nowa_probka(self):
        m, clock, sent = make_manager()
        d = {"type": "DATA", "node_id": "node_1", "sequence": 7, "config_version": 1,
             "generated_ns": 1, "value": 20.5, "unit": "degC"}
        m.process(d, clock()); m.process(dict(d), clock())
        m._files["data_log.csv"].flush()
        rows = read_csv(os.path.join(m.tmp, "data_log.csv"))
        self.assertEqual([r["duplicate"] for r in rows], ["0", "1"])
        self.assertEqual(analyze.management_overhead([], rows)["data_packets"], 2)   # pakiety liczone wszystkie

    def test_ponowienie_tego_samego_command_id_i_rezygnacja(self):
        m, clock, sent = make_manager()
        m.process(status(1), clock())
        e = m.entries["node_1"]
        e.queue.append(("sample_period_ms", 1000, "t")); m.pump(e, clock())
        for _ in range(3):                                      # 3 ponowienia
            clock.advance(1.1); m.tick(clock())
        configs = [msg for _, msg in sent if msg["type"] == "CONFIG"]
        self.assertEqual(len(configs), 4)
        self.assertEqual({c["command_id"] for c in configs}, {"cmd_001"})    # to samo polecenie
        clock.advance(1.1); m.tick(clock())
        self.assertIsNone(e.pending_command_id)
        self.assertEqual(m.commands["cmd_001"]["state"], "GAVE_UP")
        self.assertIn("COMMAND_TIMEOUT", [r["event_type"] for r in self.events(m)])
        self.assertEqual(e.sample_period_ms, 500)               # nigdy nie zgadujemy, że zadziałało

    def test_niespojnosc_bez_polecenia_uruchamia_odtworzenie(self):
        m, clock, sent = make_manager()
        m.process(status(1, version=1), clock())
        e = m.entries["node_1"]
        e.queue.append(("sample_period_ms", 1000, "t")); m.pump(e, clock())
        m.process(ack("cmd_001", 2), clock())
        # node zgłasza starą wersję (np. po restarcie) - brak polecenia w locie
        m.process(status(2, version=1, period=500), clock())
        types = [r["event_type"] for r in self.events(m)]
        self.assertIn("CONFIG_MISMATCH", types)
        self.assertIn("RESTORE_SCHEDULED", types)
        restore = [msg for _, msg in sent if msg["type"] == "CONFIG"][-1]
        self.assertEqual((restore["parameter"], restore["value"], restore["config_version"]),
                         ("sample_period_ms", 1000, 2))
        self.assertNotEqual(restore["command_id"], "cmd_001")   # nowe polecenie, nowy command_id

    def test_czas_niespojnosci_konfiguracji(self):
        m, clock, sent = make_manager()
        m.process(status(1), clock())
        e = m.entries["node_1"]
        e.queue.append(("sample_period_ms", 1000, "t")); m.pump(e, clock())
        clock.advance(0.5)
        m.process(ack("cmd_001", 2), clock())
        self.assertAlmostEqual(analyze.mismatch_time_ms(self.events(m), "node_1"), 500.0, places=3)

    def test_strategia_adaptacyjna_na_podstawie_obserwacji(self):
        m, clock, sent = make_manager("adaptive")
        m.process(status(1, battery=60.0), clock())
        self.assertEqual([s for s in sent if s[1]["type"] == "CONFIG"], [])        # >50: bez zmian
        m.process(status(2, battery=49.9), clock())
        first = sent[-1][1]
        self.assertEqual((first["parameter"], first["value"]), ("operating_state", "DEGRADED"))
        # drugi zamiar (okres) czeka, aż pierwszy dostanie ACK: max 1 polecenie w locie
        self.assertEqual(len([s for s in sent if s[1]["type"] == "CONFIG"]), 1)
        m.process(ack(first["command_id"], 2), clock())
        second = sent[-1][1]
        self.assertEqual((second["parameter"], second["value"]), ("sample_period_ms", 1000))
        m.process(ack(second["command_id"], 3), clock())
        m.process(status(3, "DEGRADED", battery=45.0, period=1000, version=3), clock())
        self.assertEqual(len([s for s in sent if s[1]["type"] == "CONFIG"]), 2)     # brak powtórek
        m.process({"type": "ALERT", "node_id": "node_1", "alert_type": "LOW_BATTERY", "value": 19.9,
                   "threshold": 20.0, "timestamp_ns": 1}, clock())
        self.assertEqual(sent[-1][1]["value"], "SLEEP")

    def test_adaptacyjna_dokladnie_na_progach(self):
        for battery, expected in ((50.0, "DEGRADED"), (20.0, "SLEEP")):
            m, clock, sent = make_manager("adaptive")
            m.process(status(1, battery=battery), clock())
            self.assertEqual(sent[-1][1]["value"], expected, battery)

    def test_brak_zarzadzania_nie_wysyla_polecen(self):
        m, clock, sent = make_manager("none")
        m.process(status(1, battery=5.0), clock())
        self.assertEqual(sent, [])

    def test_uszkodzone_i_nieznane_komunikaty(self):
        m, clock, sent = make_manager()
        m.process({"type": "STATUS", "node_id": "node_1"}, clock())             # brak pól
        m.process(status(1, node="node_99"), clock())                           # nieznany node
        m.process({"type": "NIEZNANY"}, clock())
        self.assertEqual(m.counts["malformed"], 2)
        self.assertEqual(m.counts["unknown_node"], 1)

    def test_node_ktory_nigdy_sie_nie_odezwal_jest_unreachable(self):
        m, clock, sent = make_manager()
        m.process(status(1, node="node_1"), clock())            # node_2 milczy od początku
        clock.advance(5.5); m.tick(clock())
        self.assertEqual(m.entries["node_2"].observed_state, "UNKNOWN")
        clock.advance(1.0); m.tick(clock())
        self.assertEqual(m.entries["node_2"].observed_state, wc.UNREACHABLE)
        ev = [r for r in self.events(m) if r["event_type"] == "NODE_UNREACHABLE" and r["node_id"] == "node_2"]
        self.assertIn("never_reported", ev[0]["details"])

    def test_zle_typy_pol_nie_zabijaja_sinka(self):
        m, clock, sent = make_manager()
        bad = status(1)
        bad["status_sequence"] = "x"                              # string zamiast liczby
        m.process(bad, clock())
        bad2 = status(2); bad2["battery_level"] = True            # bool zamiast liczby
        m.process(bad2, clock())
        self.assertEqual(m.counts["malformed"], 2)
        m.process(status(3), clock())                             # poprawny STATUS nadal działa
        self.assertEqual(m.entries["node_1"].last_status_seq, 3)

    def test_wyjatek_w_obsludze_nie_zatrzymuje_sinka(self):
        m, clock, sent = make_manager()
        m.on_status = lambda *a: 1 / 0
        m.process(status(1), clock())
        self.assertEqual(m.counts["handler_errors"], 1)
        self.assertIn("HANDLER_ERROR", [r["event_type"] for r in self.events(m)])

    def test_status_log_ma_stan_obserwowany_po_aktualizacji(self):
        m, clock, sent = make_manager()
        m.process(status(1, "ACTIVE"), clock())
        m.process(status(2, "FAILED", battery=0.0), clock())
        m._files["status_log.csv"].flush()
        rows = read_csv(os.path.join(m.tmp, "status_log.csv"))
        self.assertEqual([(r["operating_state"], r["observed_state"]) for r in rows],
                         [("ACTIVE", "ACTIVE"), ("FAILED", "FAILED")])

    def test_zmiana_trybu_samonaprawa_po_utracie_drugiego_polecenia(self):
        """Tryb = dwa polecenia (stan, potem okres). Gdy drugie przepadnie, kolejny STATUS to wykrywa
        i sink ponawia brakujący zamiar (nowym command_id)."""
        m, clock, sent = make_manager("adaptive")
        m.process(status(1, battery=49.0), clock())
        first = sent[-1][1]
        m.process(ack(first["command_id"], 2), clock())          # stan zmieniony
        second = sent[-1][1]
        self.assertEqual(second["parameter"], "sample_period_ms")
        for _ in range(5):                                        # okres: 4 wysłania bez odpowiedzi -> rezygnacja
            clock.advance(1.1); m.tick(clock())
        self.assertIsNone(m.entries["node_1"].pending_command_id)
        n_before = len([s for s in sent if s[1]["type"] == "CONFIG"])
        m.process(status(2, "DEGRADED", battery=48.0, period=500, version=1), clock())   # node nie dostał okresu
        again = sent[-1][1]
        self.assertGreater(len([s for s in sent if s[1]["type"] == "CONFIG"]), n_before)
        self.assertEqual((again["parameter"], again["value"]), ("sample_period_ms", 1000))
        self.assertNotEqual(again["command_id"], second["command_id"])

    def test_odtwarzanie_konfiguracji_jest_ograniczone(self):
        m, clock, sent = make_manager(max_restore_attempts=2)
        m.process(status(1, version=1), clock())
        e = m.entries["node_1"]
        e.queue.append(("sample_period_ms", 1000, "t")); m.pump(e, clock())
        m.process(ack("cmd_001", 2), clock())
        seq = 2
        for _ in range(6):                                        # node ciągle zgłasza starą wersję
            m.process(status(seq, version=1), clock()); seq += 1
            e.pending_command_id = None                           # polecenie odtworzenia "przepadło"
        types = [r["event_type"] for r in self.events(m)]
        self.assertEqual(types.count("RESTORE_SCHEDULED"), 2)
        self.assertEqual(types.count("RESTORE_GAVE_UP"), 1)

    def test_stala_wartosc_timeoutu_gdy_adaptacja_wylaczona(self):
        m, clock, sent = make_manager(adaptive_timeout=False)
        m.process(status(1), clock())
        e = m.entries["node_1"]
        e.queue.append(("status_period_ms", 10000, "t")); m.pump(e, clock())
        m.process(ack("cmd_001", 2), clock())
        clock.advance(7); m.tick(clock())
        self.assertEqual(e.observed_state, wc.UNREACHABLE)        # dokładnie 6 s jak w instrukcji

    def test_narzut_zarzadzania(self):
        mg = [{"event_type": e, "timestamp_ns": "1", "node_id": "n", "command_id": "", "details": ""}
              for e in ["STATUS_RECEIVED"] * 3 + ["COMMAND_SENT", "ACK_RECEIVED", "CONFIG_RESTORED", "NODE_UNREACHABLE"]]
        data = [{"timestamp_ns": "1"}] * 15
        o = analyze.management_overhead(mg, data)
        self.assertEqual((o["management_packets"], o["data_packets"]), (5, 15))   # zdarzenia nie-pakietowe pomijamy
        self.assertAlmostEqual(o["overhead"], 5 / 20)


class TestMetrykiAnalizy(unittest.TestCase):
    def test_dostepnosc(self):
        meta = {"start_ns": 0, "time_scale": 1.0}
        st = [{"node_id": "n", "timestamp_ns": str(int(t * SEC)), "operating_state": s}
              for t, s in ((0, "STARTING"), (1, "ACTIVE"), (6, "FAILED"))]
        mg = [{"node_id": "n", "event_type": "NODE_UNREACHABLE", "timestamp_ns": str(12 * SEC)}]
        # dostępny tylko w ACTIVE: 1..6 = 5 s z 10 s
        self.assertAlmostEqual(analyze.availability(st, mg, "n", meta, 10.0), 0.5)

    def test_czasy_w_stanach(self):
        trace = [{"t_sym_s": "0", "state": "STARTING"}, {"t_sym_s": "1", "state": "ACTIVE"},
                 {"t_sym_s": "5", "state": "DEGRADED"}, {"t_sym_s": "8", "state": "SLEEP"}]
        st = analyze.state_times(trace, 10.0)
        self.assertEqual((st["STARTING"], st["ACTIVE"], st["DEGRADED"], st["SLEEP"]), (1, 4, 3, 2))
        st5 = analyze.state_times(trace, 6.0)
        self.assertEqual((st5["ACTIVE"], st5["DEGRADED"]), (4, 1))


# --------------------------------------------------------------------------
class TestIntegracja(unittest.TestCase):
    """Prawdziwe procesy: sink-manager + 3 nody przez UDP, scenariusz testu wspólnego rdzenia."""

    def test_rdzen_ack_error_duplikat(self):
        import run_experiment
        out = tempfile.mkdtemp()
        try:
            run_experiment.run("config/rdzen/sink.json", out)
            log = read_csv(os.path.join(out, "management_log.csv"))
            by = lambda ev: [r for r in log if r["event_type"] == ev]
            ack1 = [r for r in by("ACK_RECEIVED") if r["command_id"] == "cmd_001"]
            self.assertEqual((ack1[0]["result"], ack1[0]["config_version"]), ("APPLIED", "2"))
            err = [r for r in by("ERROR_RECEIVED") if r["command_id"] == "cmd_002"]
            self.assertEqual(err[0]["result"], "VALUE_OUT_OF_RANGE")
            self.assertTrue(any("duplicate" in r["details"] for r in by("ERROR_RECEIVED")))
            truth = read_json(os.path.join(out, "node_1_truth.json"))
            self.assertEqual(truth["commands"]["commands_applied"], 3)       # cmd_001, cmd_003, cmd_004
            self.assertEqual(truth["commands"]["duplicates_ignored"], 2)     # cmd_002 i cmd_003 ponownie
            self.assertEqual(truth["config_version"], 4)                     # stary duplikat cmd_003 nie cofnął wersji
            table = read_csv(os.path.join(out, "state_table.csv"))
            row = [r for r in table if r["node_id"] == "node_1"][0]
            # duplikat cmd_003 (1500) po cmd_004 (2000): gdyby wykonano go ponownie, okres wróciłby do 1500
            self.assertEqual((row["sample_period_ms"], row["reported_config_version"]), ("2000", "4"))
            for n in ("node_2", "node_3"):                                   # inne nody nietknięte
                t = read_json(os.path.join(out, f"{n}_truth.json"))
                self.assertEqual(t["config_version"], 1)
            data = read_csv(os.path.join(out, "data_log.csv"))
            for n in ("node_1", "node_2", "node_3"):                         # sink odebrał wszystko (localhost)
                t = read_json(os.path.join(out, f"{n}_truth.json"))
                self.assertEqual(len([r for r in data if r["node_id"] == n and r["duplicate"] == "0"]),
                                 t["sent_data"])
            # księgowanie energii: każdy STATUS (także STARTING i STOPPED) i każdy pomiar kosztują
            t2 = read_json(os.path.join(out, "node_2_truth.json"))
            expected = 100 - 0.60 * t2["sent_data"] - 0.25 * t2["status_sent"]
            self.assertAlmostEqual(t2["final_battery"], expected, places=3)
        finally:
            shutil.rmtree(out, ignore_errors=True)

    def test_stratny_node_ponowienia_bez_podwojnego_wykonania(self):
        """node_1 gubi 40% poleceń i 40% odpowiedzi, node_3 jest głuchy: sink ponawia TO SAMO command_id,
        node wykonuje każde polecenie co najwyżej raz, a głuchy node kończy na GAVE_UP."""
        import run_experiment
        out = tempfile.mkdtemp()
        try:
            run_experiment.run("config/strat/sink.json", out)
            log = read_csv(os.path.join(out, "management_log.csv"))
            self.assertGreater(len([r for r in log if r["event_type"] == "COMMAND_TIMEOUT"]), 0)
            sent = [r for r in log if r["event_type"] == "COMMAND_SENT" and r["command_id"]
                    and r["node_id"] == "node_1"]
            self.assertTrue({r["command_id"] for r in sent if r["details"].startswith("retry=")})
            t = read_json(os.path.join(out, "node_1_truth.json"))
            self.assertEqual(t["config_version"], 1 + t["commands"]["commands_applied"])
            self.assertLessEqual(t["commands"]["commands_applied"], len({r["command_id"] for r in sent}))
            self.assertGreater(t["commands"]["duplicates_ignored"], 0)
            # głuchy node_3: rezygnacja po ponowieniach, ograniczone odtwarzanie, wersja bez zmian
            gave = [r for r in log if r["node_id"] == "node_3" and r["result"] == "GAVE_UP"]
            self.assertTrue(any(r["event_type"] == "COMMAND_TIMEOUT" for r in gave))
            self.assertTrue(any(r["event_type"] == "RESTORE_GAVE_UP" for r in gave))
            self.assertEqual(read_json(os.path.join(out, "node_3_truth.json"))["config_version"], 1)
        finally:
            shutil.rmtree(out, ignore_errors=True)


if __name__ == "__main__":
    unittest.main(verbosity=2)
