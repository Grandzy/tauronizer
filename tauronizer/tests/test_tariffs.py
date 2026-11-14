from __future__ import annotations

from datetime import date, datetime, timezone

import pytest

from tauronizer.tariffs import (
    PRESETS,
    TZ,
    TariffValidationError,
    compile_zones,
    easter_sunday,
    holidays_between,
    parse_interval,
    polish_holidays,
    zone_for,
)


def preset(preset_id: str) -> dict:
    for item in PRESETS:
        if item["id"] == preset_id:
            return item
    raise AssertionError(preset_id)


def local(year: int, month: int, day: int, hour: int, minute: int = 0) -> datetime:
    return datetime(year, month, day, hour, minute, tzinfo=TZ)


def test_parse_interval() -> None:
    assert parse_interval("06:00-13:00") == (360, 780)
    assert parse_interval("00:00-24:00") == (0, 1440)
    assert parse_interval(" 22:00 – 24:00 ") == (1320, 1440)


@pytest.mark.parametrize(
    "value",
    ["6-13", "06:30-13:00", "13:00-06:00", "24:00-06:00", "06:00-25:00", "06:00-06:00"],
)
def test_parse_interval_rejects_invalid(value: str) -> None:
    with pytest.raises(TariffValidationError):
        parse_interval(value)


def test_easter() -> None:
    assert easter_sunday(2024) == date(2024, 3, 31)
    assert easter_sunday(2025) == date(2025, 4, 20)
    assert easter_sunday(2026) == date(2026, 4, 5)


def test_polish_holidays() -> None:
    holidays = polish_holidays(2026)
    assert date(2026, 1, 1) in holidays
    assert date(2026, 1, 6) in holidays
    assert date(2026, 4, 6) in holidays  # Poniedziałek Wielkanocny
    assert date(2026, 5, 24) in holidays  # Zielone Świątki
    assert date(2026, 6, 4) in holidays  # Boże Ciało
    assert date(2026, 12, 26) in holidays
    assert date(2026, 12, 24) in holidays
    assert date(2024, 12, 24) not in polish_holidays(2024)


def test_holidays_between_spans_years() -> None:
    holidays = holidays_between(date(2025, 12, 20), date(2026, 1, 10))
    assert date(2025, 12, 25) in holidays
    assert date(2026, 1, 6) in holidays


@pytest.mark.parametrize("item", PRESETS, ids=[item["id"] for item in PRESETS])
def test_presets_compile(item: dict) -> None:
    zones = compile_zones(item["config"])
    assert zones
    assert zones[-1].intervals == ((0, 1440),)


def test_coverage_rejects_gap() -> None:
    config = {
        "zones": [
            {
                "id": "peak",
                "name": "Szczyt",
                "days": [0, 1, 2, 3, 4],
                "intervals": ["06:00-22:00"],
                "energy_net": 0.5,
                "distribution_net": 0.3,
            }
        ]
    }
    with pytest.raises(TariffValidationError, match="nie pokrywa"):
        compile_zones(config)


def test_g12w_weekend_and_holiday_are_offpeak() -> None:
    zones = compile_zones(preset("g12w")["config"])
    holidays = holidays_between(date(2026, 1, 1), date(2026, 1, 31))

    # Monday 10:00 -> peak
    assert zone_for(local(2026, 1, 5, 10), zones, holidays).id == "szczyt"
    # Saturday 10:00 -> off-peak
    assert zone_for(local(2026, 1, 10, 10), zones, holidays).id == "pozaszczyt"
    # Tuesday 6 January (holiday) 10:00 -> off-peak
    assert zone_for(local(2026, 1, 6, 10), zones, holidays).id == "pozaszczyt"
    # Monday 14:00 -> off-peak
    assert zone_for(local(2026, 1, 5, 14), zones, holidays).id == "pozaszczyt"


def test_g12_holiday_is_peak_if_weekday() -> None:
    zones = compile_zones(preset("g12")["config"])
    holidays = holidays_between(date(2026, 1, 1), date(2026, 1, 31))
    assert zone_for(local(2026, 1, 6, 10), zones, holidays).id == "szczyt"


def test_g13_peak_splits() -> None:
    zones = compile_zones(preset("g13")["config"])
    holidays = holidays_between(date(2026, 1, 1), date(2026, 12, 31))

    # Winter weekday: morning peak 07-13, evening peak 16-21.
    assert zone_for(local(2026, 1, 5, 8), zones, holidays).id == "szczyt_przedpoludniowy"
    assert zone_for(local(2026, 1, 5, 18), zones, holidays).id == "szczyt_popoudniowy_zima"
    assert zone_for(local(2026, 1, 5, 14), zones, holidays).id == "pozaszczyt"
    assert zone_for(local(2026, 1, 5, 15), zones, holidays).id == "pozaszczyt"
    assert zone_for(local(2026, 1, 5, 21), zones, holidays).id == "pozaszczyt"

    # Summer weekday: morning peak 07-13, evening peak 19-22.
    assert zone_for(local(2026, 7, 6, 8), zones, holidays).id == "szczyt_przedpoludniowy"
    assert zone_for(local(2026, 7, 6, 18), zones, holidays).id == "pozaszczyt"
    assert zone_for(local(2026, 7, 6, 20), zones, holidays).id == "szczyt_popoudniowy_lato"
    assert zone_for(local(2026, 7, 6, 22), zones, holidays).id == "pozaszczyt"

    # Weekend and holiday are off-peak in both seasons.
    assert zone_for(local(2026, 1, 10, 18), zones, holidays).id == "pozaszczyt"
    assert zone_for(local(2026, 7, 11, 20), zones, holidays).id == "pozaszczyt"
    assert zone_for(local(2026, 1, 6, 18), zones, holidays).id == "pozaszczyt"


def test_months_restrict_zone() -> None:
    config = {
        "zones": [
            {
                "id": "lato",
                "name": "Lato",
                "days": [0, 1, 2, 3, 4, 5, 6],
                "intervals": ["00:00-24:00"],
                "months": [4, 5, 6, 7, 8, 9],
                "energy_net": 0.5,
                "distribution_net": 0.3,
            },
            {
                "id": "zima",
                "name": "Zima",
                "days": [0, 1, 2, 3, 4, 5, 6],
                "intervals": ["00:00-24:00"],
                "months": [1, 2, 3, 10, 11, 12],
                "energy_net": 0.3,
                "distribution_net": 0.2,
            },
        ]
    }
    zones = compile_zones(config)
    holidays: set[date] = set()
    assert zone_for(local(2026, 7, 1, 12), zones, holidays).id == "lato"
    assert zone_for(local(2026, 1, 1, 12), zones, holidays).id == "zima"
    assert zone_for(local(2026, 12, 31, 23), zones, holidays).id == "zima"


def test_coverage_rejects_seasonal_gap() -> None:
    config = {
        "zones": [
            {
                "id": "caly_rok",
                "name": "Cały rok",
                "days": [0, 1, 2, 3, 4, 5, 6],
                "intervals": ["00:00-24:00"],
                "months": list(range(1, 12)),
                "energy_net": 0.5,
                "distribution_net": 0.3,
            }
        ]
    }
    with pytest.raises(TariffValidationError, match="nie pokrywa"):
        compile_zones(config)


@pytest.mark.parametrize("months", [[], [0], [13], ["styczeń"]])
def test_invalid_months_are_rejected(months: list) -> None:
    config = {
        "zones": [
            {
                "id": "strefa",
                "name": "Strefa",
                "days": [0, 1, 2, 3, 4, 5, 6],
                "intervals": ["00:00-24:00"],
                "months": months,
                "energy_net": 0.5,
                "distribution_net": 0.3,
            }
        ]
    }
    with pytest.raises(TariffValidationError):
        compile_zones(config)


def test_dst_boundary_uses_local_time() -> None:
    zones = compile_zones(preset("g12")["config"])
    holidays: set[date] = set()

    # 2026-03-29: DST starts. 01:30 UTC == 03:30 CEST (Sunday -> off-peak).
    utc_dt = datetime(2026, 3, 29, 1, 30, tzinfo=timezone.utc)
    local_dt = utc_dt.astimezone(TZ)
    assert local_dt.hour == 3
    assert zone_for(local_dt, zones, holidays).id == "pozaszczyt"

    # 2026-10-25: DST ends. 01:30 UTC == 02:30 CET (Sunday -> off-peak).
    utc_dt = datetime(2026, 10, 25, 1, 30, tzinfo=timezone.utc)
    local_dt = utc_dt.astimezone(TZ)
    assert local_dt.hour == 2
    assert zone_for(local_dt, zones, holidays).id == "pozaszczyt"


def test_zone_prices_are_non_negative() -> None:
    for item in PRESETS:
        for zone in compile_zones(item["config"]):
            assert zone.energy_net >= 0
            assert zone.distribution_net >= 0


@pytest.mark.parametrize("day", [10, 11])
def test_g12_weekend_daytime_is_day_zone(day):
    zones = compile_zones(preset("g12")["config"])
    assert zone_for(local(2026, 1, day, 10), zones, set()).id == "szczyt"


@pytest.mark.parametrize("preset_id", ["g12w", "g13"])
def test_christmas_eve_is_offpeak(preset_id):
    zones = compile_zones(preset(preset_id)["config"])
    holidays = holidays_between(date(2026, 12, 24), date(2026, 12, 24))
    assert zone_for(local(2026, 12, 24, 10), zones, holidays).id == "pozaszczyt"


def test_verified_2026_net_prices():
    expected = {
        "g11": [(0.497, 0.2464)],
        "g12": [(0.543, 0.2841), (0.413, 0.0558)],
        "g12w": [(0.622, 0.3298), (0.413, 0.0512)],
        "g13": [(0.4668, 0.2203), (0.778, 0.3898), (0.778, 0.3898), (0.421, 0.0392)],
    }
    for item in PRESETS:
        config = item["config"]
        assert [(z["energy_net"], z["distribution_net"]) for z in config["zones"]] == expected[item["id"]]
        assert [fee["net_per_kwh"] for fee in config["variable_fees"]] == [0.0332, 0.0073, 0.003]
        assert config["excise_net_per_kwh"] == 0.005
        assert config["capacity_fee"]["net_monthly_rates"] == [4.29, 10.31, 17.18, 24.05]
