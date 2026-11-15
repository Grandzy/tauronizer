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
    is_default: bool = False
    kompas_level: int | None = None

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

    dynamic = config.get('zone_source') == 'pse_kompas'
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

        is_default = not dynamic and (bool(raw.get("is_default")) or (
            days == set(range(7)) and months is None
            and intervals == ((0, 1440),) and not raw.get("exclude_holidays", False)
        ))
        if is_default and any(zone.is_default for zone in zones):
            raise TariffValidationError("Taryfa może mieć tylko jedną strefę domyślną (całodobową przez cały rok).")
        if is_default:
            days, intervals, months = set(range(7)), ((0, 1440),), None

        zones.append(
            CompiledZone(
                id=zone_id,
                name=name,
                days=frozenset(days),
                intervals=intervals,
                energy_net=energy,
                distribution_net=distribution,
                exclude_holidays=False if is_default else bool(raw.get("exclude_holidays", False)),
                is_default=is_default,
                kompas_level=raw.get("kompas_level") if dynamic else None,
                months=months,
            )
        )

    if dynamic:
        levels = [zone.kompas_level for zone in zones]
        if len(levels) != 4 or any(type(level) is not int for level in levels) or set(levels) != {0, 1, 2, 3}:
            raise TariffValidationError('G14dynamic wymaga dokładnie czterech stref Kompasu S1–S4.')
        return sorted(zones, key=lambda zone: zone.kompas_level)
    zones.sort(key=lambda zone: zone.is_default)
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
    return ({date(year, 12, 24)} if year >= 2025 else set()) | {
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
    dynamic_levels: Mapping[str, int] | None = None,
) -> CompiledZone:
    """Return the first matching zone for a local timestamp."""

    if zones and zones[0].kompas_level is not None:
        from .kompas import utc_key
        from .db import kompas_level
        key = utc_key(local_dt)
        level = dynamic_levels.get(key) if dynamic_levels is not None else kompas_level(key)
        for zone in zones:
            if zone.kompas_level == level:
                return zone
        raise TariffValidationError(f'Brak strefy Kompasu PSE dla {local_dt.isoformat()}. Sprawdź import danych w zakładce Taryfy.')
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

# Verified 2026-11-14 against URE tariff 265/2025 and TAURON distribution tariff.
# Full sources and assumptions: README.md, section "Stawki Tauron 2026".
PRESET_NOTE = (
    "G14dynamic: cennik Prąd ze zmienną dystrybucją, godzinowe strefy Kompasu PSE. "
    "TAURON Sprzedaż 2026 (bez obszaru gliwickiego i ofert rynkowych), "
    "dystrybucja według stawek od 01.02.2026. Wszystkie stawki netto; "
    "energia bez akcyzy. Domyślnie 3 fazy i abonament 0 zł (nienaliczany od 01.10.2026). "
    "Opłata mocowa: próg według wpisanego poboru lub szacunku rocznego z analizy. "
    "Porównanie stosuje skonfigurowany cennik do całego zakresu, nie odtwarza faktur historycznych."
)

_FIXED_FEES = [
    {"name": "Opłata stała sieciowa (3 fazy)", "net_monthly": 10.86},
    {"name": "Opłata abonamentowa (nienaliczana od 01.10.2026)", "net_monthly": 0.0},
    {"name": "Opłata handlowa", "net_monthly": 0.00},
]

_VARIABLE_FEES = [
    {"name": "Opłata jakościowa", "net_per_kwh": 0.0332},
    {"name": "Opłata OZE", "net_per_kwh": 0.0073},
    {"name": "Opłata kogeneracyjna", "net_per_kwh": 0.0030},
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
        "capacity_fee": {"annual_kwh": None, "net_monthly_rates": [4.29, 10.31, 17.18, 24.05]},
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
                    energy=0.4970,
                    distribution=0.2464,
                )
            ]
        ),
    },
    {
        "id": "g12",
        "name": "Tauron G12",
        "description": (
            "Dwie strefy: dzienna 06–13 i 15–22 oraz nocna 13–15 i 22–06. "
            "Te same godziny we wszystkie dni, także weekendy i święta."
        ),
        "config": _config(
            [
                _zone(
                    "szczyt",
                    "Szczyt",
                    days=_ALL_DAYS,
                    intervals=["06:00-13:00", "15:00-22:00"],
                    energy=0.5430,
                    distribution=0.2841,
                ),
                _zone(
                    "pozaszczyt",
                    "Pozostałe godziny — strefa domyślna",
                    days=_ALL_DAYS,
                    intervals=["00:00-24:00"],
                    energy=0.4130,
                    distribution=0.0558,
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
                    energy=0.6220,
                    distribution=0.3298,
                    exclude_holidays=True,
                ),
                _zone(
                    "pozaszczyt",
                    "Pozostałe godziny — strefa domyślna",
                    days=_ALL_DAYS,
                    intervals=["00:00-24:00"],
                    energy=0.4130,
                    distribution=0.0512,
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
                    energy=0.4668,
                    distribution=0.2203,
                    exclude_holidays=True,
                ),
                _zone(
                    "szczyt_popoudniowy_zima",
                    "Szczyt popołudniowy (zima)",
                    days=_WORKDAYS,
                    intervals=["16:00-21:00"],
                    energy=0.7780,
                    distribution=0.3898,
                    exclude_holidays=True,
                    months=[10, 11, 12, 1, 2, 3],
                ),
                _zone(
                    "szczyt_popoudniowy_lato",
                    "Szczyt popołudniowy (lato)",
                    days=_WORKDAYS,
                    intervals=["19:00-22:00"],
                    energy=0.7780,
                    distribution=0.3898,
                    exclude_holidays=True,
                    months=[4, 5, 6, 7, 8, 9],
                ),
                _zone(
                    "pozaszczyt",
                    "Pozostałe godziny — strefa domyślna",
                    days=_ALL_DAYS,
                    intervals=["00:00-24:00"],
                    energy=0.4210,
                    distribution=0.0392,
                ),
            ]
        ),
    },
]

KOMPAS_ZONE_DESCRIPTIONS = {
    0: 'Najniższa stawka dystrybucji. Dobry moment na przesunięcie pracy urządzeń, np. ładowania auta, grzania wody lub zmywarki.',
    1: 'Standardowa stawka dystrybucji. Możesz korzystać z energii normalnie; przesunięcie zużycia do S1 może dodatkowo obniżyć koszt.',
    2: 'Podwyższona stawka dystrybucji. Warto ograniczyć zużycie lub przełożyć pracę urządzeń na tańszą godzinę.',
    3: 'Najwyższa stawka dystrybucji. Szczególnie warto ograniczyć pobór i przełożyć energochłonne czynności na inną godzinę.',
}

# Official 2026 rates; the offer's 0.5020 net includes 0.0050 excise.
_g14 = _config([
    {**_zone(f's{level+1}', name, days=_ALL_DAYS, intervals=['00:00-24:00'],
             energy=0.4970, distribution=rate), 'kompas_level': level,
     'description': KOMPAS_ZONE_DESCRIPTIONS[level]}
    for level, name, rate in [
        (0, 'Zalecane użytkowanie (S1)', 0.0224),
        (1, 'Normalne użytkowanie (S2)', 0.0893),
        (2, 'Zalecane oszczędzanie (S3)', 0.3881),
        (3, 'Wymagane ograniczenie (S4)', 2.3756),
    ]
])
_g14['zone_source'] = 'pse_kompas'
_g14['fixed_fees'] = [fee for fee in _g14['fixed_fees'] if 'abonamentowa' not in fee['name']]
PRESETS.append({'id': 'g14dynamic', 'name': 'Tauron G14dynamic',
    'description': 'Cztery strefy dystrybucji według godzinowych wskazań Kompasu PSE. Cena energii stała według cennika Prąd ze zmienną dystrybucją 2026; porównanie wymaga danych Kompasu w lokalnej bazie.',
    'config': _g14})
PRESET_VERSION = 6


def preset_by_id(preset_id: str) -> dict[str, Any] | None:
    for preset in PRESETS:
        if preset["id"] == preset_id:
            return preset
    return None
