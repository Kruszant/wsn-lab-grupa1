"""Wspólne elementy laboratorium WSN (Grupa 1 - zarządzanie energią i cyklem pracy).

Zawiera: kontrakt komunikatów (JSON przez UDP), walidację poleceń CONFIG, zegar
symulacji, wczytywanie konfiguracji oraz pomocnicze funkcje energii.

UWAGI O PUŁAPKACH, które ten moduł rozwiązuje:
  * ZEGARY. Wszystkie czasy mierzymy `time.perf_counter_ns()` (zegar monotoniczny,
    wspólny dla procesów na jednym komputerze). Nigdy nie mieszamy go z time.time().
    Czas reakcji na polecenie liczymy WYŁĄCZNIE na zegarze sinka (nie z pól noda).
  * ENERGIA liczymy w liczbach CAŁKOWITYCH (jednostki 0.001), bo na floatach
    100 - 500*0.1 potrafi dać 50.00000000000001 i progi (>50, <=20) zadziałałyby źle.
  * `bool` w Pythonie jest podtypem `int` (isinstance(True, int) == True), więc
    wartość `true` w JSON nie może przejść jako poprawny okres próbkowania.
"""
import json
import time

HOST = "127.0.0.1"
SINK_PORT = 6000
NODE_PORTS = {"node_1": 6101, "node_2": 6102, "node_3": 6103}

STATES = ("STARTING", "ACTIVE", "SLEEP", "DEGRADED", "FAILED", "STOPPED")
SETTABLE_STATES = ("ACTIVE", "DEGRADED", "SLEEP")     # które stany sink może ustawić
OPERATING_STATES = SETTABLE_STATES                    # stany, w których node mierzy i wysyła
UNREACHABLE = "UNREACHABLE"                           # stan OBSERWOWANY przez sink (nie stan noda!)

# ruch zarządczy wg polecenia: STATUS, CONFIG, COMMAND, ACK, ERROR, ALERT
MGMT_TYPES = ("STATUS", "CONFIG", "COMMAND", "ACK", "ERROR", "ALERT")

# zakresy parametrów, które sink może zmieniać (granice włącznie)
PARAM_RULES = {
    "sample_period_ms": (100, 5000),      # wymagane w poleceniu: 100 <= x <= 5000
    "status_period_ms": (500, 20000),     # zakres wybrany przez nas (polecenie go nie podaje)
}

ENERGY_UNITS = 1000                       # 1.0 energii = 1000 jednostek całkowitych

# wymagane pola komunikatów (kontrakt)
REQUIRED_FIELDS = {
    "DATA": ("node_id", "sequence", "config_version", "generated_ns", "value", "unit"),
    "STATUS": ("node_id", "status_sequence", "timestamp_ns", "operating_state", "battery_level",
               "sample_period_ms", "sent_packets", "config_version"),
    "CONFIG": ("command_id", "destination", "parameter", "value", "config_version", "sent_ns"),
    "ACK": ("command_id", "node_id", "result", "config_version", "timestamp_ns"),
    "ERROR": ("command_id", "node_id", "reason", "current_config_version"),
    "ALERT": ("node_id", "alert_type", "value", "threshold", "timestamp_ns"),
}


# oczekiwane typy pól (bool odrzucamy zawsze - patrz is_int)
_INT_FIELDS = ("sequence", "status_sequence", "config_version", "generated_ns", "timestamp_ns",
               "sample_period_ms", "sent_packets", "current_config_version")
_STR_FIELDS = ("node_id", "unit", "operating_state", "command_id", "result", "reason", "alert_type",
               "destination", "parameter")
_NUM_FIELDS = ("value", "battery_level", "threshold")


def bad_types(msg: dict) -> list:
    """Pola o złym typie (np. status_sequence jako string). Komunikat z takim polem odrzucamy,
    zamiast pozwolić, by wyjątek zatrzymał pętlę odbioru sinka."""
    bad = [f for f in _INT_FIELDS if f in msg and not is_int(msg[f])]
    bad += [f for f in _STR_FIELDS if f in msg and not isinstance(msg[f], str)]
    if msg.get("type") != "CONFIG":              # w CONFIG `value` bywa tekstem (operating_state)
        bad += [f for f in _NUM_FIELDS if f in msg and (isinstance(msg[f], bool)
                or not isinstance(msg[f], (int, float)))]
    return bad


def now_ns() -> int:
    """Jedyny zegar projektu: monotoniczny, w nanosekundach."""
    return time.perf_counter_ns()


# --------------------------------------------------------------------------
# kodowanie komunikatów
# --------------------------------------------------------------------------
def encode(msg: dict) -> bytes:
    return json.dumps(msg, separators=(",", ":")).encode("utf-8")


def decode(data: bytes):
    """Zwraca słownik albo None dla uszkodzonego / niepoprawnego komunikatu (bez wyjątku)."""
    try:
        msg = json.loads(data.decode("utf-8"))
    except (ValueError, UnicodeDecodeError):
        return None
    return msg if isinstance(msg, dict) and isinstance(msg.get("type"), str) else None


def missing_fields(msg: dict) -> list:
    """Lista brakujących pól wymaganych dla danego typu komunikatu."""
    return [f for f in REQUIRED_FIELDS.get(msg.get("type"), ()) if f not in msg]


def is_int(value) -> bool:
    """Liczba całkowita, ale NIE bool (pułapka: True == 1 w Pythonie)."""
    return isinstance(value, int) and not isinstance(value, bool)


# --------------------------------------------------------------------------
# walidacja polecenia CONFIG (po stronie noda) - czysta funkcja, łatwa do testów
# --------------------------------------------------------------------------
def validate_config(msg: dict, node_id: str, current_version: int, node_state: str):
    """Zwraca None gdy polecenie jest poprawne, w przeciwnym razie powód odrzucenia.

    Kolejność kontroli ma znaczenie - ZANIM cokolwiek zmienimy, sprawdzamy wszystko."""
    if missing_fields(msg):
        return "MALFORMED_COMMAND"
    if msg["destination"] != node_id:
        return "WRONG_DESTINATION"
    if node_state not in OPERATING_STATES:
        return "NODE_NOT_READY" if node_state == "STARTING" else "NODE_NOT_OPERATIONAL"
    param, value = msg["parameter"], msg["value"]
    if param in PARAM_RULES:
        if not is_int(value):
            return "INVALID_VALUE_TYPE"
        lo, hi = PARAM_RULES[param]
        if not lo <= value <= hi:
            return "VALUE_OUT_OF_RANGE"
    elif param == "operating_state":
        if not isinstance(value, str) or value not in SETTABLE_STATES:
            return "INVALID_STATE_VALUE"
    else:
        return "UNKNOWN_PARAMETER"
    if not is_int(msg["config_version"]) or msg["config_version"] <= current_version:
        return "STALE_CONFIG_VERSION"
    return None


# --------------------------------------------------------------------------
# energia (liczby całkowite)
# --------------------------------------------------------------------------
def to_units(x: float) -> int:
    return round(x * ENERGY_UNITS)


def battery_mode(battery_level: float, degraded_below: float = 50.0, sleep_below: float = 20.0):
    """Tryb wynikający z reguł adaptacyjnych (progi w CAŁKOWITYCH jednostkach):

        battery > 50:        ACTIVE
        20 < battery <= 50:  DEGRADED
        battery <= 20:       SLEEP
    """
    u = to_units(battery_level)
    if u > to_units(degraded_below):
        return "ACTIVE"
    if u > to_units(sleep_below):
        return "DEGRADED"
    return "SLEEP"


# --------------------------------------------------------------------------
# zegar symulacji (przyspieszenie) i konfiguracja
# --------------------------------------------------------------------------
class SimClock:
    """Przelicza czas rzeczywisty na czas symulacji: t_sym = t_real * time_scale.

    Okresy z konfiguracji i protokołu (np. sample_period_ms = 500) są zawsze w
    CZASIE SYMULACJI. Do uśpienia procesu dzielimy je przez time_scale."""

    def __init__(self, time_scale: float, start_ns: int):
        self.scale = float(time_scale)
        self.start_ns = start_ns

    def sim_s(self, ns: int) -> float:
        """Moment ns (zegar perf_counter) -> sekundy symulacji od startu."""
        return (ns - self.start_ns) * 1e-9 * self.scale

    def real_ns(self, sim_ms: float) -> int:
        """Czas trwania w ms symulacji -> nanosekundy rzeczywiste."""
        return int(sim_ms * 1e6 / self.scale)

    def sim_ms(self, real_ns: int) -> float:
        return real_ns * 1e-6 * self.scale


def load_config(path: str, required: dict) -> dict:
    """Wczytuje JSON i sprawdza wymagane pola (nazwa -> typ lub krotka typów)."""
    with open(path, encoding="utf-8") as f:
        cfg = json.load(f)
    problems = []
    for name, typ in required.items():
        if name not in cfg:
            problems.append(f"brak pola '{name}'")
        elif not isinstance(cfg[name], typ) or isinstance(cfg[name], bool) and typ is not bool:
            problems.append(f"pole '{name}' ma zły typ")
    if problems:
        raise ValueError(f"Błędna konfiguracja {path}: " + "; ".join(problems))
    return cfg
