"""Cost calculation engine for Tauronizer."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date, datetime, timedelta
from typing import Any, Sequence

from .tariffs import (
    CompiledZone,
    TZ,
    TariffValidationError,
    compile_zones,
    holidays_between,
    zone_for,
)

DAYS_PER_YEAR = 365.25


@dataclass(frozen=True)
class ConsumptionSample:
    """Energy consumed during an interval, in kWh."""

    timestamp: datetime  # aware, UTC
    kwh: float


def _round(value: float, digits: int = 2) -> float:
    return round(float(value) + 1e-9, digits)


def capacity_fee_details(
    config: dict[str, Any], total_kwh: float, days: int
) -> dict[str, Any] | None:
    fee = config.get("capacity_fee")
    if fee is None:
        return None  # Older/custom tariffs retain their explicit fee configuration.
    annual_kwh = fee.get("annual_kwh")
    estimated = annual_kwh is None
    if estimated:
        annual_kwh = total_kwh * DAYS_PER_YEAR / days
    annual_kwh = float(annual_kwh)
    tier = 0 if annual_kwh < 500 else 1 if annual_kwh <= 1200 else 2 if annual_kwh <= 2800 else 3
    return {
        "annual_kwh": _round(annual_kwh, 3),
        "estimated": estimated,
        "tier": tier,
        "net_monthly": float(fee["net_monthly_rates"][tier]),
    }


def _tariff_meta(tariff: dict[str, Any]) -> dict[str, Any]:
    return {
        "tariff_id": tariff["id"],
        "name": tariff["name"],
        "description": tariff.get("description", ""),
        "is_preset": bool(tariff.get("is_preset")),
        "preset_id": tariff.get("preset_id"),
    }


def _empty_result(tariff: dict[str, Any], message: str) -> dict[str, Any]:
    return {
        **_tariff_meta(tariff),
        "error": message,
        "total_pln": None,
        "annual_pln": None,
        "per_kwh_pln": None,
        "extra_cost_pln": None,
        "rank": None,
        "breakdown": None,
        "zones": [],
    }


def _cost_for_tariff(
    tariff: dict[str, Any],
    zones: Sequence[CompiledZone],
    local_samples: Sequence[tuple[datetime, float]],
    holidays: set[date],
    total_kwh: float,
    days: int,
    dynamic_levels: dict[str, int] | None = None,
) -> dict[str, Any]:
    totals: dict[str, float] = {zone.id: 0.0 for zone in zones}
    for local_dt, kwh in local_samples:
        zone = zone_for(local_dt, zones, holidays, dynamic_levels)
        totals[zone.id] += kwh

    config = tariff["config"]
    energy_pln = sum(totals[zone.id] * zone.energy_net for zone in zones)
    distribution_pln = sum(totals[zone.id] * zone.distribution_net for zone in zones)

    variable_fees = config.get("variable_fees") or []
    variable_rate = sum(float(fee.get("net_per_kwh", 0) or 0) for fee in variable_fees)
    variable_fees_pln = total_kwh * variable_rate

    excise_rate = float(config.get("excise_net_per_kwh", 0) or 0)
    excise_pln = total_kwh * excise_rate

    fixed_fees = config.get("fixed_fees") or []
    fixed_monthly = sum(float(fee.get("net_monthly", 0) or 0) for fee in fixed_fees)
    months = days * 12 / DAYS_PER_YEAR
    fixed_pln = fixed_monthly * months
    capacity = capacity_fee_details(config, total_kwh, days)
    capacity_monthly = capacity["net_monthly"] if capacity else 0.0
    capacity_pln = capacity_monthly * months

    net_pln = _round(
        energy_pln + distribution_pln + variable_fees_pln + excise_pln + fixed_pln + capacity_pln
    )
    vat_rate = float(config.get("vat_percent", 23) or 0) / 100
    vat_pln = _round(net_pln * vat_rate)
    total_pln = net_pln + vat_pln

    annual_factor = DAYS_PER_YEAR / days if days else 0
    annual_variable = (
        energy_pln + distribution_pln + variable_fees_pln + excise_pln
    ) * annual_factor
    annual_net = annual_variable + (fixed_monthly + capacity_monthly) * 12
    annual_pln = annual_net * (1 + vat_rate)

    zone_rows = []
    for zone in zones:
        kwh = totals[zone.id]
        zone_rows.append(
            {
                "id": zone.id,
                "name": zone.name,
                "kwh": _round(kwh, 3),
                "share_percent": _round((kwh / total_kwh * 100) if total_kwh else 0, 1),
                "price_energy_net": zone.energy_net,
                "price_distribution_net": zone.distribution_net,
                "energy_pln": _round(kwh * zone.energy_net),
                "distribution_pln": _round(kwh * zone.distribution_net),
            }
        )

    return {
        **_tariff_meta(tariff),
        "error": None,
        "total_pln": _round(total_pln),
        "annual_pln": _round(annual_pln),
        "per_kwh_pln": _round(total_pln / total_kwh, 4) if total_kwh else 0,
        "extra_cost_pln": None,
        "rank": None,
        "capacity_fee": capacity,
        "breakdown": {
            "energy_pln": _round(energy_pln),
            "distribution_pln": _round(distribution_pln),
            "variable_fees_pln": _round(variable_fees_pln),
            "excise_pln": _round(excise_pln),
            "fixed_pln": _round(fixed_pln),
            "capacity_fee_pln": _round(capacity_pln),
            "net_pln": _round(net_pln),
            "vat_pln": _round(vat_pln),
            "total_pln": _round(total_pln),
        },
        "zones": zone_rows,
    }


def analyze(
    tariffs: Sequence[dict[str, Any]],
    samples: Sequence[ConsumptionSample],
    start_date: date,
    end_date: date,
) -> dict[str, Any]:
    """Compare the cost of every tariff for a consumption profile.

    ``samples`` must already be filtered to the requested range. A sample's
    timestamp is the beginning of the interval it describes.
    """

    days = (end_date - start_date).days + 1
    if days < 1:
        raise ValueError("Zakres dat jest nieprawidłowy.")

    total_kwh = sum(max(sample.kwh, 0.0) for sample in samples)
    holidays = holidays_between(start_date, end_date)

    local_samples: list[tuple[datetime, float]] = []
    weekday_hour = [[0.0 for _ in range(24)] for _ in range(7)]
    monthly: dict[str, float] = {}

    for sample in samples:
        kwh = max(sample.kwh, 0.0)
        local_dt = sample.timestamp.astimezone(TZ)
        local_samples.append((local_dt, kwh))
        weekday_hour[local_dt.weekday()][local_dt.hour] += kwh
        monthly[local_dt.strftime("%Y-%m")] = monthly.get(local_dt.strftime("%Y-%m"), 0.0) + kwh

    dynamic_levels = None
    if any(tariff['config'].get('zone_source') == 'pse_kompas' for tariff in tariffs):
        from .db import kompas_levels
        dynamic_levels = kompas_levels()
    results: list[dict[str, Any]] = []
    for tariff in tariffs:
        try:
            zones = compile_zones(tariff["config"])
            results.append(
                _cost_for_tariff(
                    tariff, zones, local_samples, holidays, total_kwh, days, dynamic_levels
                )
            )
        except TariffValidationError as exc:
            results.append(_empty_result(tariff, str(exc)))
        except Exception as exc:  # defensive: one bad tariff must not kill the report
            results.append(_empty_result(tariff, f"Nie udało się policzyć taryfy: {exc}"))

    valid = [item for item in results if item["error"] is None]
    invalid = [item for item in results if item["error"] is not None]
    valid.sort(key=lambda item: (item["total_pln"], item["name"].casefold()))

    cheapest_total = valid[0]["total_pln"] if valid else None
    for rank, item in enumerate(valid, start=1):
        item["rank"] = rank
        item["extra_cost_pln"] = _round(item["total_pln"] - cheapest_total) if cheapest_total is not None else None

    is_tie = (
        len(valid) > 1
        and (valid[1]["total_pln"] - valid[0]["total_pln"]) < 0.01
    )
    max_savings = (
        valid[-1]["total_pln"] - valid[0]["total_pln"] if len(valid) > 1 else 0.0
    )
    profile_max = max((value for row in weekday_hour for value in row), default=0.0)

    return {
        "start": start_date.isoformat(),
        "end": end_date.isoformat(),
        "days": days,
        "total_kwh": _round(total_kwh, 3),
        "sample_count": len(samples),
        "tariffs": valid + invalid,
        "cheapest_tariff_id": valid[0]["tariff_id"] if valid else None,
        "cheapest_tariff_name": valid[0]["name"] if valid else None,
        "most_expensive_tariff_id": valid[-1]["tariff_id"] if valid else None,
        "max_savings_pln": _round(max_savings),
        "is_tie": is_tie,
        "profile": {
            "weekday_hour_kwh": [
                [_round(value, 3) for value in row] for row in weekday_hour
            ],
            "max_cell_kwh": _round(profile_max, 3),
        },
        "monthly_kwh": [
            {"month": month, "kwh": _round(value, 3)}
            for month, value in sorted(monthly.items())
        ],
        "methodology": (
            "Zużycie pochodzi ze statystyk długoterminowych Home Assistant "
            "(okresy godzinowe). Każdą godzinę przypisano do strefy na podstawie "
            "czasu lokalnego Europe/Warsaw, z uwzględnieniem weekendów i świąt. "
            f"Opłaty miesięczne rozliczono proporcjonalnie ({days} dni, 365,25 dni/rok). "
            "Opłata mocowa jest miesięcznym ryczałtem według progu poboru podanego "
            "w taryfie; bez podanej wartości próg oszacowano z zużycia × 365,25/liczba dni. "
            "To szacunek porównawczy, nie kwalifikacja według odczytów Taurona. "
            "Wszystkie składniki i akcyzę zsumowano netto; VAT doliczono raz do sumy. "
            "Skonfigurowane stawki obowiązują w całej symulacji, niezależnie od dat zużycia."
        ),
    }


def inclusive_end_date(end_exclusive: datetime) -> date:
    """Helper for callers that work with half-open date ranges."""

    return (end_exclusive - timedelta(microseconds=1)).date()
