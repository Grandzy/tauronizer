from __future__ import annotations

from datetime import date, datetime, timezone

import pytest

from tauronizer.calc import ConsumptionSample, analyze
from tauronizer.tariffs import PRESETS, TZ


def tariff(preset_id: str, tariff_id: str | None = None) -> dict:
    item = next(preset for preset in PRESETS if preset["id"] == preset_id)
    return {
        "id": tariff_id or item["id"],
        "name": item["name"],
        "description": item["description"],
        "preset_id": item["id"],
        "is_preset": True,
        "config": item["config"],
    }


def sample(local_hour: datetime, kwh: float) -> ConsumptionSample:
    return ConsumptionSample(timestamp=local_hour.astimezone(timezone.utc), kwh=kwh)


def day_samples(day: date, peak_kwh: float = 2.0, night_kwh: float = 4.0) -> list[ConsumptionSample]:
    return [
        sample(datetime(day.year, day.month, day.day, 10, tzinfo=TZ), peak_kwh),
        sample(datetime(day.year, day.month, day.day, 20, tzinfo=TZ), peak_kwh),
        sample(datetime(day.year, day.month, day.day, 3, tzinfo=TZ), night_kwh),
    ]


def test_g11_totals_and_breakdown() -> None:
    samples = day_samples(date(2026, 1, 5))
    result = analyze([tariff("g11")], samples, date(2026, 1, 5), date(2026, 1, 5))

    assert result["total_kwh"] == 8.0
    assert result["days"] == 1
    cost = result["tariffs"][0]
    assert cost["error"] is None
    assert cost["total_pln"] == pytest.approx(9.20, abs=0.01)
    assert cost["per_kwh_pln"] == pytest.approx(1.15, abs=0.005)
    breakdown = cost["breakdown"]
    assert breakdown["energy_pln"] == pytest.approx(3.98, abs=0.01)
    assert breakdown["distribution_pln"] == pytest.approx(1.97, abs=0.01)
    assert breakdown["variable_fees_pln"] == pytest.approx(0.35, abs=0.01)
    assert breakdown["fixed_pln"] == pytest.approx(0.36, abs=0.01)
    assert sum(
        [
            breakdown["energy_pln"],
            breakdown["distribution_pln"],
            breakdown["variable_fees_pln"],
            breakdown["excise_pln"],
            breakdown["fixed_pln"],
            breakdown["capacity_fee_pln"],
            breakdown["vat_pln"],
        ]
    ) == pytest.approx(breakdown["total_pln"], abs=0.03)


def test_g12_is_cheaper_for_night_consumption() -> None:
    samples = day_samples(date(2026, 1, 5))
    result = analyze(
        [tariff("g11"), tariff("g12")],
        samples,
        date(2026, 1, 5),
        date(2026, 1, 5),
    )
    assert result["cheapest_tariff_id"] == "g12"
    sorted_tariffs = result["tariffs"]
    assert sorted_tariffs[0]["rank"] == 1
    assert sorted_tariffs[0]["extra_cost_pln"] == 0
    assert sorted_tariffs[1]["extra_cost_pln"] > 0
    assert result["max_savings_pln"] > 0

    g12 = next(item for item in sorted_tariffs if item["tariff_id"] == "g12")
    zones = {zone["id"]: zone for zone in g12["zones"]}
    assert zones["szczyt"]["kwh"] == 4.0
    assert zones["pozaszczyt"]["kwh"] == 4.0
    assert zones["szczyt"]["share_percent"] == 50.0


def test_holiday_is_offpeak_in_g12w() -> None:
    holiday = date(2026, 1, 6)  # Tuesday, Trzech Króli
    samples = day_samples(holiday)
    result = analyze(
        [tariff("g12"), tariff("g12w")],
        samples,
        holiday,
        holiday,
    )
    g12w = next(item for item in result["tariffs"] if item["tariff_id"] == "g12w")
    zones = {zone["id"]: zone for zone in g12w["zones"]}
    assert zones["szczyt"]["kwh"] == 0.0
    assert zones["pozaszczyt"]["kwh"] == 8.0


def test_annual_estimate_is_stable_for_repeated_days() -> None:
    one_day = analyze([tariff("g11")], day_samples(date(2026, 1, 5)), date(2026, 1, 5), date(2026, 1, 5))
    two_day_samples = day_samples(date(2026, 1, 5)) + day_samples(date(2026, 1, 6))
    two_days = analyze([tariff("g11")], two_day_samples, date(2026, 1, 5), date(2026, 1, 6))

    assert two_days["total_kwh"] == 16.0
    assert one_day["tariffs"][0]["annual_pln"] == pytest.approx(
        two_days["tariffs"][0]["annual_pln"], abs=0.02
    )


def test_profile_and_months() -> None:
    samples = day_samples(date(2026, 1, 5)) + day_samples(date(2026, 2, 2))
    result = analyze([tariff("g11")], samples, date(2026, 1, 1), date(2026, 2, 28))

    profile = result["profile"]["weekday_hour_kwh"]
    assert len(profile) == 7
    assert all(len(row) == 24 for row in profile)
    assert profile[0][10] == pytest.approx(4.0, abs=0.001)
    assert [row["month"] for row in result["monthly_kwh"]] == ["2026-01", "2026-02"]


def test_zero_consumption_does_not_crash() -> None:
    result = analyze([tariff("g11")], [], date(2026, 1, 5), date(2026, 1, 5))
    assert result["total_kwh"] == 0
    cost = result["tariffs"][0]
    assert cost["per_kwh_pln"] == 0
    assert cost["total_pln"] > 0  # fixed fees still apply


def test_broken_tariff_is_reported_not_fatal() -> None:
    broken = tariff("g11", tariff_id="broken")
    broken["config"] = {"zones": [], "fixed_fees": [], "variable_fees": []}
    result = analyze(
        [broken, tariff("g11")],
        day_samples(date(2026, 1, 5)),
        date(2026, 1, 5),
        date(2026, 1, 5),
    )
    assert result["cheapest_tariff_id"] == "g11"
    assert result["tariffs"][0]["error"] is None
    assert result["tariffs"][-1]["tariff_id"] == "broken"
    assert result["tariffs"][-1]["error"]


def test_negative_samples_are_ignored() -> None:
    samples = day_samples(date(2026, 1, 5)) + [
        sample(datetime(2026, 1, 5, 12, tzinfo=TZ), -3.0)
    ]
    result = analyze([tariff("g11")], samples, date(2026, 1, 5), date(2026, 1, 5))
    assert result["total_kwh"] == 8.0


def test_invalid_range() -> None:
    with pytest.raises(ValueError):
        analyze([tariff("g11")], [], date(2026, 1, 6), date(2026, 1, 5))


@pytest.mark.parametrize("annual_kwh,rate", [
    (0, 4.29), (499.999, 4.29), (500, 10.31), (1200, 10.31),
    (1200.001, 17.18), (2800, 17.18), (2800.001, 24.05), (10000, 24.05),
])
def test_capacity_tier_boundaries(annual_kwh, rate):
    from copy import deepcopy
    item = deepcopy(tariff("g11"))
    item["config"]["capacity_fee"]["annual_kwh"] = annual_kwh
    result = analyze([item], day_samples(date(2026, 1, 5)), date(2026, 1, 5), date(2026, 1, 5))
    cost = result["tariffs"][0]
    assert cost["capacity_fee"]["net_monthly"] == rate
    assert cost["capacity_fee"]["estimated"] is False
    assert cost["breakdown"]["capacity_fee_pln"] == round(rate * 12 / 365.25, 2)


def test_capacity_estimate_and_custom_rates():
    from copy import deepcopy
    item = deepcopy(tariff("g11"))
    item["config"]["capacity_fee"]["net_monthly_rates"] = [1, 2, 3, 4]
    result = analyze([item], day_samples(date(2026, 1, 5)), date(2026, 1, 5), date(2026, 1, 5))
    fee = result["tariffs"][0]["capacity_fee"]
    assert fee == {"annual_kwh": 2922, "estimated": True, "tier": 3, "net_monthly": 4}


def test_net_components_then_single_vat_and_annual_capacity():
    # Independent contract example, no dependence on preset prices.
    item = tariff("g11")
    item["config"] = {
        "zones": [{"id": "all", "name": "All", "days": list(range(7)),
                   "intervals": ["00:00-24:00"], "energy_net": 0.5, "distribution_net": 0.2}],
        "fixed_fees": [{"name": "Sieć", "net_monthly": 10}],
        "variable_fees": [{"name": "Dodatki", "net_per_kwh": 0.03}],
        "excise_net_per_kwh": 0.005,
        "vat_percent": 23,
        "capacity_fee": {"annual_kwh": 1200, "net_monthly_rates": [4.29, 10.31, 17.18, 24.05]},
    }
    result = analyze([item], [sample(datetime(2026, 1, 5, 10, tzinfo=TZ), 100)], date(2026, 1, 1), date(2026, 12, 31))
    cost = result["tariffs"][0]
    # 50 energy + 20 distribution + 3 extras + 0.5 excise + monthly fees prorated.
    expected_net = round(73.5 + (10 + 10.31) * 365 * 12 / 365.25, 2)
    assert cost["breakdown"]["net_pln"] == expected_net
    assert cost["breakdown"]["vat_pln"] == round(expected_net * 0.23, 2)
    assert cost["total_pln"] == round(expected_net + round(expected_net * 0.23, 2), 2)
    assert cost["annual_pln"] == round((73.5 * 365.25 / 365 + 20.31 * 12) * 1.23, 2)
    item["config"]["vat_percent"] = 0
    no_vat = analyze([item], [sample(datetime(2026, 1, 5, 10, tzinfo=TZ), 100)], date(2026, 1, 1), date(2026, 12, 31))["tariffs"][0]
    assert no_vat["total_pln"] == expected_net
    assert no_vat["breakdown"]["vat_pln"] == 0


def test_legacy_tariff_without_capacity_is_not_charged_automatically():
    from copy import deepcopy
    item = deepcopy(tariff("g11"))
    del item["config"]["capacity_fee"]
    cost = analyze([item], [], date(2026, 1, 1), date(2026, 12, 31))["tariffs"][0]
    assert cost["capacity_fee"] is None
    assert cost["breakdown"]["capacity_fee_pln"] == 0


def test_month_weekday_profile_keeps_years_and_local_dates():
    samples = [
        sample(datetime(2025, 12, 31, 23, tzinfo=TZ), 2),
        sample(datetime(2026, 1, 1, 0, tzinfo=TZ), 3),
        sample(datetime(2026, 1, 1, 1, tzinfo=TZ), -5),
    ]
    result = analyze([tariff('g11')], samples, date(2025, 12, 31), date(2026, 1, 2))
    december, january = result['month_weekday_profile']
    assert december['month'] == '2025-12'
    assert december['weekday_kwh'] == [0, 0, 2, 0, 0, 0, 0]
    assert january['weekday_kwh'] == [0, 0, 0, 3, 0, 0, 0]
    assert january['weekday_sample_count'][3] == 2
    assert sum(sum(row['weekday_kwh']) for row in result['month_weekday_profile']) == result['total_kwh']


def simple_monthly_tariff(identifier, rate, fixed=0):
    return {'id': identifier, 'name': identifier, 'config': {
        'zones': [{'id': 'all', 'name': 'All', 'days': list(range(7)),
                   'intervals': ['00:00-24:00'], 'energy_net': rate, 'distribution_net': 0.2}],
        'variable_fees': [{'name': 'Variable', 'net_per_kwh': 0.03}],
        'excise_net_per_kwh': 0.005, 'vat_percent': 23,
        'fixed_fees': [{'name': 'Fixed', 'net_monthly': fixed}],
    }}


def test_monthly_costs_use_analysis_winner_and_include_current_outside_ranking():
    current = simple_monthly_tariff('current', 0.5, 30)
    competitor = simple_monthly_tariff('other', 1.0)
    samples = [sample(datetime(2026, 1, 5, 10, tzinfo=TZ), 100),
               sample(datetime(2026, 2, 5, 10, tzinfo=TZ), 10)]
    result = analyze([competitor], samples, date(2026, 1, 1), date(2026, 2, 28), current_tariff=current)
    assert [t['tariff_id'] for t in result['tariffs']] == ['other']
    january, february = result['monthly_costs']
    assert january['recommended']['tariff_id'] == result['cheapest_tariff_id'] == 'other'
    assert february['recommended']['tariff_id'] == 'other'
    assert january['current']['total_pln'] < january['recommended']['total_pln']
    expected_net = round(100 * .735 + 30 * 31 * 12 / 365.25, 2)
    assert january['current']['total_pln'] == round(expected_net + round(expected_net * .23, 2), 2)
    assert result['current_tariff_id'] == 'current'


def test_monthly_costs_use_partial_days_and_one_capacity_tier_for_whole_analysis():
    current = simple_monthly_tariff('current', 0.5, 10)
    current['config']['capacity_fee'] = {'annual_kwh': None, 'net_monthly_rates': [1, 10, 100, 1000]}
    samples = [sample(datetime(2026, 1, 31, 10, tzinfo=TZ), 100),
               sample(datetime(2026, 2, 1, 10, tzinfo=TZ), 0)]
    result = analyze([current], samples, date(2026, 1, 31), date(2026, 2, 28), current_tariff=current)
    assert result['tariffs'][0]['capacity_fee']['net_monthly'] == 100
    jan, feb = result['monthly_costs']
    assert (jan['days'], feb['days']) == (1, 28)
    expected_feb_net = round(110 * 28 * 12 / 365.25, 2)
    assert feb['current']['total_pln'] == round(expected_feb_net + round(expected_feb_net * .23, 2), 2)
    assert sum(row['current']['total_pln'] for row in result['monthly_costs']) == pytest.approx(result['tariffs'][0]['total_pln'], abs=.03)


def test_monthly_costs_distinguish_missing_statistics_from_zero_consumption():
    current = simple_monthly_tariff('current', .5, 10)
    samples = [sample(datetime(2026, 2, 5, 10, tzinfo=TZ), 0)]
    result = analyze([current], samples, date(2026, 1, 1), date(2026, 2, 28), current_tariff=current)
    jan, feb = result['monthly_costs']
    assert jan['current']['total_pln'] is None
    assert jan['recommended']['total_pln'] is None
    assert jan['current']['error']
    assert feb['current']['total_pln'] > 0
    assert feb['sample_count'] == 1


def test_monthly_dynamic_failure_does_not_hide_other_months(monkeypatch):
    from tauronizer import db
    from tauronizer.kompas import utc_key
    first = datetime(2026, 1, 5, 10, tzinfo=TZ)
    monkeypatch.setattr(db, 'kompas_levels', lambda: {utc_key(first): 0})
    current = tariff('g14dynamic')
    result = analyze([tariff('g11')], [sample(first, 10), sample(datetime(2026, 2, 5, 10, tzinfo=TZ), 10)],
                     date(2026, 1, 1), date(2026, 2, 28), current_tariff=current)
    jan, feb = result['monthly_costs']
    assert jan['current']['total_pln'] is not None
    assert feb['current']['total_pln'] is None
    assert feb['recommended']['tariff_id'] == 'g11'
    assert feb['unavailable_tariffs'][0]['tariff_id'] == 'g14dynamic'


def test_sixteen_month_chart_keeps_same_analysis_winner_even_when_monthly_winner_differs():
    current = simple_monthly_tariff('current', 1.0)
    proposed = simple_monthly_tariff('proposed', .5, 30)
    samples = []
    for index in range(16):
        year, month = 2025 + index // 12, index % 12 + 1
        samples.append(sample(datetime(year, month, 5, 10, tzinfo=TZ), 10 if index == 15 else 100))
    result = analyze([current, proposed], samples, date(2025, 1, 1), date(2026, 4, 30), current_tariff=current)
    assert result['monthly_costs_basis'] == 'analysis'
    assert result['cheapest_tariff_id'] == 'proposed'
    assert len(result['monthly_costs']) == 16
    assert {row['recommended']['tariff_id'] for row in result['monthly_costs']} == {'proposed'}
    assert result['monthly_costs'][-1]['current']['total_pln'] < result['monthly_costs'][-1]['recommended']['total_pln']
    winner = result['tariffs'][0]
    assert sum(row['recommended']['total_pln'] for row in result['monthly_costs']) == pytest.approx(winner['total_pln'], abs=.16)
