"""Tariff definitions, time-zone rules and Polish holiday handling.

The module is deliberately dependency-free so the tariff engine can be tested
and reasoned about without Home Assistant.
"""

from __future__ import annotations

import copy
import re
from dataclasses import dataclass
from datetime import date, datetime, timedelta
from typing import Any, Iterable, Mapping, Sequence
from zoneinfo import ZoneInfo

TZ = ZoneInfo("Europe/Warsaw")

DAY_NAMES = (
    "poniedziałek",
    "wtorek",
    "środa",
    "czwartek",
    "piątek",
    "sobota",
    "niedziela",
)
DAY_SHORT = ("Pn", "Wt", "Śr", "Cz", "Pt", "So", "Nd")

INTERVAL_RE = re.compile(r"^(\d{1,2}):(\d{2})-(\d{1,2}):(\d{2})$")


class TariffValidationError(ValueError):
    """Raised when a tariff configuration cannot be used for calculations."""


@dataclass(frozen=True)
class CompiledZone:
    """A single, ordered tariff zone rule.

    Rules are evaluated in the order they are defined. The first matching rule
    wins, which is why every tariff needs a catch-all fallback zone.
    """

    id: str
    name: str
    days: frozenset[int]
    intervals: tuple[tuple[int, int], ...]
    energy_net: float
    distribution_net: float
    exclude_holidays: bool
    months: frozenset[int] | None = None

    def matches(
        self, month: int, weekday: int, minutes: int, is_holiday: bool
    ) -> bool:
        if self.months is not None and month not in self.months:
            return False
        if self.exclude_holidays and is_holiday:
            return False
        if weekday not in self.days:
            return False
        return any(start <= minutes < end for start, end in self.intervals)


def parse_interval(value: str) -> tuple[int, int]:
    """Parse ``HH:MM-HH:MM`` into minute offsets.

    Only full hours are accepted: statistics are hourly and a tariff boundary
    in the middle of an hour could not be priced accurately.
    """

    text = str(value).strip().replace("–", "-").replace("—", "-")
    text = text.replace(" ", "")
    match = INTERVAL_RE.match(text)
    if not match:
        raise TariffValidationError(
            f"Nieprawidłowy przedział godzinowy „{value}”. Użyj formatu 06:00-13:00."
        )

    start_h, start_m, end_h, end_m = (int(part) for part in match.groups())

    if start_h == 24 or end_h > 24 or start_m > 59 or end_m > 59:
        raise TariffValidationError(f"Nieprawidłowa godzina w przedziale „{value}”.")
    if start_h == 24 and start_m == 0:
        raise TariffValidationError("Przedział nie może zaczynać się o 24:00.")
    if start_m or end_m:
        raise TariffValidationError(
            f"Przedział „{value}” musi zaczynać się i kończyć o pełnej godzinie."
        )
    if end_h == 24 and end_m != 0:
        raise TariffValidationError("Godzina 24:00 jest dozwolona tylko jako koniec przedziału.")

    start = start_h * 60 + start_m
    end = end_h * 60 + end_m
    if start >= end:
        raise TariffValidationError(
            f"Przedział „{value}” jest pusty. Dla godzin nocnych dodaj np. 00:00-06:00 i 22:00-24:00."
        )
    return start, end


def compile_zones(config: Mapping[str, Any]) -> list[CompiledZone]:
    """Validate a tariff config and compile its zones."""

    raw_zones = config.get("zones")
    if not isinstance(raw_zones, list) or not raw_zones:
        raise TariffValidationError("Taryfa musi zawierać co najmniej jedną strefę.")

    zones: list[CompiledZone] = []
    seen_ids: set[str] = set()

    for index, raw in enumerate(raw_zones, start=1):
        if not isinstance(raw, Mapping):
            raise TariffValidationError(f"Strefa nr {index} ma nieprawidłowy format.")
        zone_id = str(raw.get("id", "")).strip()
        name = str(raw.get("name", "")).strip()
        if not zone_id:
            raise TariffValidationError(f"Strefa nr {index} nie ma identyfikatora.")
        if zone_id in seen_ids:
            raise TariffValidationError(f"Identyfikator strefy „{zone_id}” powtarza się.")
        seen_ids.add(zone_id)
        if not name:
            raise TariffValidationError(f"Strefa „{zone_id}” nie ma nazwy.")

        days_raw = raw.get("days", list(range(7)))
        if not isinstance(days_raw, (list, tuple, set)) or not days_raw:
            raise TariffValidationError(f"Strefa „{name}” musi obejmować co najmniej jeden dzień.")
        days: set[int] = set()
        for day in days_raw:
            if not isinstance(day, int) or not 0 <= day <= 6:
                raise TariffValidationError(
                    f"Strefa „{name}” ma nieprawidłowy dzień tygodnia: {day!r}."
                )
            days.add(day)

        intervals_raw = raw.get("intervals")
        if not isinstance(intervals_raw, list) or not intervals_raw:
            raise TariffValidationError(f"Strefa „{name}” nie ma żadnego przedziału godzinowego.")
        intervals = tuple(parse_interval(value) for value in intervals_raw)

        months_raw = raw.get("months")
        months: frozenset[int] | None = None
        if months_raw is not None:
            if not isinstance(months_raw, (list, tuple, set)) or not months_raw:
                raise TariffValidationError(
                    f"Strefa „{name}”: lista miesięcy nie może być pusta."
                )
            month_set: set[int] = set()
            for month in months_raw:
                if not isinstance(month, int) or not 1 <= month <= 12:
                    raise TariffValidationError(
                        f"Strefa „{name}” ma nieprawidłowy miesiąc: {month!r}. "
                        "Użyj liczb od 1 (styczeń) do 12 (grudzień)."
                    )
                month_set.add(month)
            # All twelve months is the same as no restriction.
            if len(month_set) < 12:
                months = frozenset(month_set)

        try:
            energy = float(raw.get("energy_net", 0))
            distribution = float(raw.get("distribution_net", 0))
        except (TypeError, ValueError) as exc:
            raise TariffValidationError(
                f"Strefa „{name}” ma nieprawidłową cenę energii lub dystrybucji."
            ) from exc
        if energy < 0 or distribution < 0:
            raise TariffValidationError(f"Strefa „{name}” ma ujemną cenę.")
        if energy > 10 or distribution > 10:
            raise TariffValidationError(
                f"Strefa „{name}”: cena powyżej 10 zł/kWh wygląda na pomyłkę."
            )

        zones.append(
            CompiledZone(
                id=zone_id,
                name=name,
                days=frozenset(days),
                intervals=intervals,
                energy_net=energy,
                distribution_net=distribution,
                exclude_holidays=bool(raw.get("exclude_holidays", False)),
                months=months,
            )
        )

    _validate_coverage(zones)
    return zones


def _validate_coverage(zones: Sequence[CompiledZone]) -> None:
    """Ensure every hour of every day is covered, also on holidays.

    Seasonal zones (``months``) are checked month by month, so a tariff that
    only covers e.g. winter evenings is still rejected for the summer.
    """

    for month in range(1, 13):
        for holiday in (False, True):
            for weekday in range(7):
                for hour in range(24):
                    minutes = hour * 60
                    if not any(
                        zone.matches(month, weekday, minutes, holiday)
                        for zone in zones
                    ):
                        suffix = " (także w święta)" if holiday else ""
                        raise TariffValidationError(
                            "Taryfa nie pokrywa całego roku: "
                            f"miesiąc {month}, {DAY_NAMES[weekday]} "
                            f"{hour:02d}:00–{hour + 1:02d}:00{suffix}. "
                            "Dodaj strefę obejmującą ten czas."
                        )


def easter_sunday(year: int) -> date:
    """Anonymous Gregorian algorithm for Easter Sunday."""

    a = year % 19
    b = year // 100
    c = year % 100
    d = b // 4
    e = b % 4
    f = (b + 8) // 25
    g = (b - f + 1) // 3
    h = (19 * a + b - d - g + 15) % 30
    i = c // 4
    k = c % 4
    l = (32 + 2 * e + 2 * i - h - k) % 7
    m = (a + 11 * h + 22 * l) // 451
    month = (h + l - 7 * m + 114) // 31
    day = ((h + l - 7 * m + 114) % 31) + 1
    return date(year, month, day)


def polish_holidays(year: int) -> set[date]:
    """Statutory Polish holidays for a given year."""

    easter = easter_sunday(year)
    return {
        date(year, 1, 1),  # Nowy Rok
        date(year, 1, 6),  # Trzech Króli
        date(year, 5, 1),  # Święto Pracy
        date(year, 5, 3),  # Konstytucji 3 Maja
        date(year, 8, 15),  # Wniebowzięcie NMP
        date(year, 11, 1),  # Wszystkich Świętych
        date(year, 11, 11),  # Niepodległości
        date(year, 12, 25),  # Boże Narodzenie
        date(year, 12, 26),  # Drugi dzień Bożego Narodzenia
        easter + timedelta(days=1),  # Poniedziałek Wielkanocny
        easter + timedelta(days=49),  # Zielone Świątki
        easter + timedelta(days=60),  # Boże Ciało
    }


def holidays_between(start: date, end: date) -> set[date]:
    """Holidays covering a date range, with a one-year margin."""

    years: Iterable[int] = range(start.year - 1, end.year + 2)
    result: set[date] = set()
    for year in years:
        result |= polish_holidays(year)
    return result


def zone_for(
    local_dt: datetime,
    zones: Sequence[CompiledZone],
    holidays: set[date],
) -> CompiledZone:
    """Return the first matching zone for a local timestamp."""

    holiday = local_dt.date() in holidays
    minutes = local_dt.hour * 60 + local_dt.minute
    for zone in zones:
        if zone.matches(local_dt.month, local_dt.weekday(), minutes, holiday):
            return zone
    raise TariffValidationError(
        f"Brak strefy taryfowej dla {local_dt.strftime('%Y-%m-%d %H:%M')}."
    )


# ---------------------------------------------------------------------------
# Built-in Tauron presets
# ---------------------------------------------------------------------------

PRESET_NOTE = (
    "Wartości przykładowe, netto, na potrzeby porównania. "
    "Przed decyzją zweryfikuj stawki z aktualnym cennikiem Tauron."
)

_FIXED_FEES = [
    {"name": "Opłata stała sieciowa", "net_monthly": 12.00},
    {"name": "Opłata abonamentowa", "net_monthly": 4.50},
]

_VARIABLE_FEES = [
    {"name": "Opłata przejściowa", "net_per_kwh": 0.0009},
    {"name": "Opłata OZE", "net_per_kwh": 0.0065},
    {"name": "Opłata kogeneracyjna", "net_per_kwh": 0.0013},
    {"name": "Opłata mocowa", "net_per_kwh": 0.0249},
]

_ALL_DAYS = [0, 1, 2, 3, 4, 5, 6]
_WORKDAYS = [0, 1, 2, 3, 4]


def _zone(
    zone_id: str,
    name: str,
    *,
    days: Sequence[int],
    intervals: Sequence[str],
    energy: float,
    distribution: float,
    exclude_holidays: bool = False,
    months: Sequence[int] | None = None,
) -> dict[str, Any]:
    zone: dict[str, Any] = {
        "id": zone_id,
        "name": name,
        "days": list(days),
        "intervals": list(intervals),
        "energy_net": energy,
        "distribution_net": distribution,
        "exclude_holidays": exclude_holidays,
    }
    if months is not None:
        zone["months"] = list(months)
    return zone


def _config(zones: Sequence[dict[str, Any]]) -> dict[str, Any]:
    return {
        "zones": list(zones),
        "fixed_fees": copy.deepcopy(_FIXED_FEES),
        "variable_fees": copy.deepcopy(_VARIABLE_FEES),
        "excise_net_per_kwh": 0.005,
        "vat_percent": 23.0,
    }


PRESETS: list[dict[str, Any]] = [
    {
        "id": "g11",
        "name": "Tauron G11",
        "description": (
            "Taryfa jednostrefowa. Jedna cena energii i dystrybucji przez całą dobę "
            "— najprostsza, ale zwykle droższa przy dużym zużyciu."
        ),
        "config": _config(
            [
                _zone(
                    "cala_doba",
                    "Cała doba",
                    days=_ALL_DAYS,
                    intervals=["00:00-24:00"],
                    energy=0.46,
                    distribution=0.30,
                )
            ]
        ),
    },
    {
        "id": "g12",
        "name": "Tauron G12",
        "description": (
            "Dwie strefy: szczyt (dni robocze 06–13 i 15–22) oraz pozaszczyt. "
            "Weekendy są w całości poza szczytem."
        ),
        "config": _config(
            [
                _zone(
                    "szczyt",
                    "Szczyt",
                    days=_WORKDAYS,
                    intervals=["06:00-13:00", "15:00-22:00"],
                    energy=0.53,
                    distribution=0.34,
                ),
                _zone(
                    "pozaszczyt",
                    "Pozaszczyt",
                    days=_ALL_DAYS,
                    intervals=["00:00-24:00"],
                    energy=0.39,
                    distribution=0.22,
                ),
            ]
        ),
    },
    {
        "id": "g12w",
        "name": "Tauron G12w",
        "description": (
            "Taryfa weekendowa: szczyt tylko w dni robocze 06–13 i 15–22, "
            "a weekendy i święta w całości w niższej strefie."
        ),
        "config": _config(
            [
                _zone(
                    "szczyt",
                    "Szczyt",
                    days=_WORKDAYS,
                    intervals=["06:00-13:00", "15:00-22:00"],
                    energy=0.53,
                    distribution=0.36,
                    exclude_holidays=True,
                ),
                _zone(
                    "pozaszczyt",
                    "Pozaszczyt",
                    days=_ALL_DAYS,
                    intervals=["00:00-24:00"],
                    energy=0.38,
                    distribution=0.21,
                ),
            ]
        ),
    },
    {
        "id": "g13",
        "name": "Tauron G13",
        "description": (
            "Trzy strefy: szczyt przedpołudniowy (dni robocze 07–13), szczyt "
            "popołudniowy (zima 16–21, lato 19–22) oraz pozaszczyt. Weekendy "
            "i święta są w całości poza szczytem."
        ),
        "config": _config(
            [
                _zone(
                    "szczyt_przedpoludniowy",
                    "Szczyt przedpołudniowy",
                    days=_WORKDAYS,
                    intervals=["07:00-13:00"],
                    energy=0.54,
                    distribution=0.35,
                    exclude_holidays=True,
                ),
                _zone(
                    "szczyt_popoudniowy_zima",
                    "Szczyt popołudniowy (zima)",
                    days=_WORKDAYS,
                    intervals=["16:00-21:00"],
                    energy=0.54,
                    distribution=0.35,
                    exclude_holidays=True,
                    months=[10, 11, 12, 1, 2, 3],
                ),
                _zone(
                    "szczyt_popoudniowy_lato",
                    "Szczyt popołudniowy (lato)",
                    days=_WORKDAYS,
                    intervals=["19:00-22:00"],
                    energy=0.54,
                    distribution=0.35,
                    exclude_holidays=True,
                    months=[4, 5, 6, 7, 8, 9],
                ),
                _zone(
                    "pozaszczyt",
                    "Pozaszczyt",
                    days=_ALL_DAYS,
                    intervals=["00:00-24:00"],
                    energy=0.36,
                    distribution=0.20,
                ),
            ]
        ),
    },
]

PRESET_VERSION = 2


def preset_by_id(preset_id: str) -> dict[str, Any] | None:
    for preset in PRESETS:
        if preset["id"] == preset_id:
            return preset
    return None
