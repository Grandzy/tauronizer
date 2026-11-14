"""Pydantic models used by the HTTP API."""

from __future__ import annotations

import re
from datetime import date
from typing import Annotated, Any

from pydantic import BaseModel, ConfigDict, Field, field_validator

ENTITY_RE = re.compile(r"^[a-z0-9_]+\.[a-z0-9_]+$")


class Zone(BaseModel):
    model_config = ConfigDict(extra="forbid")

    id: str = Field(min_length=1, max_length=40, pattern=r"^[A-Za-z0-9_-]+$")
    name: str = Field(min_length=1, max_length=80)
    days: list[int] = Field(default_factory=lambda: list(range(7)))
    intervals: list[str] = Field(min_length=1, max_length=12)
    energy_net: float = Field(ge=0, le=10)
    distribution_net: float = Field(ge=0, le=10)
    exclude_holidays: bool = False
    is_default: bool = False
    months: list[int] | None = Field(default=None, min_length=1, max_length=12)

    @field_validator("days")
    @classmethod
    def _validate_days(cls, value: list[int]) -> list[int]:
        if not value:
            raise ValueError("Strefa musi obejmować co najmniej jeden dzień tygodnia.")
        if len(set(value)) != len(value):
            raise ValueError("Dni tygodnia nie mogą się powtarzać.")
        if any(day < 0 or day > 6 for day in value):
            raise ValueError("Dni tygodnia muszą być liczbami od 0 (poniedziałek) do 6.")
        return sorted(value)

    @field_validator("months")
    @classmethod
    def _validate_months(cls, value: list[int] | None) -> list[int] | None:
        if value is None:
            return None
        if not value:
            raise ValueError("Lista miesięcy nie może być pusta.")
        if len(set(value)) != len(value):
            raise ValueError("Miesiące nie mogą się powtarzać.")
        if any(month < 1 or month > 12 for month in value):
            raise ValueError("Miesiące muszą być liczbami od 1 (styczeń) do 12 (grudzień).")
        return sorted(value)

    @field_validator("intervals")
    @classmethod
    def _validate_intervals(cls, value: list[str]) -> list[str]:
        cleaned = [item.strip() for item in value if item and item.strip()]
        if not cleaned:
            raise ValueError("Strefa musi mieć co najmniej jeden przedział godzinowy.")
        return cleaned


class FixedFee(BaseModel):
    model_config = ConfigDict(extra="forbid")

    name: str = Field(min_length=1, max_length=80)
    net_monthly: float = Field(ge=0, le=10_000)


class VariableFee(BaseModel):
    model_config = ConfigDict(extra="forbid")

    name: str = Field(min_length=1, max_length=80)
    net_per_kwh: float = Field(ge=0, le=10)


class CapacityFee(BaseModel):
    """Monthly household fee; bounds are <500, <=1200, <=2800, >2800 kWh."""

    model_config = ConfigDict(extra="forbid")

    annual_kwh: float | None = Field(default=None, ge=0, allow_inf_nan=False)
    net_monthly_rates: list[Annotated[float, Field(ge=0, le=10_000)]] = Field(
        default_factory=lambda: [4.29, 10.31, 17.18, 24.05], min_length=4, max_length=4
    )


class TariffConfig(BaseModel):
    model_config = ConfigDict(extra="forbid")

    zones: list[Zone] = Field(min_length=1, max_length=16)
    fixed_fees: list[FixedFee] = Field(default_factory=list, max_length=20)
    variable_fees: list[VariableFee] = Field(default_factory=list, max_length=20)
    capacity_fee: CapacityFee | None = None
    excise_net_per_kwh: float = Field(default=0.005, ge=0, le=1)
    vat_percent: float = Field(default=23.0, ge=0, le=100)


class TariffCreate(BaseModel):
    name: str = Field(min_length=1, max_length=80)
    description: str = Field(default="", max_length=600)
    config: TariffConfig


class TariffUpdate(TariffCreate):
    pass


class AnalyzeRequest(BaseModel):
    entity_id: str = Field(min_length=3, max_length=255)
    start: date
    end: date
    tariff_ids: list[str] = Field(default_factory=list, max_length=20)

    @field_validator("entity_id")
    @classmethod
    def _validate_entity_id(cls, value: str) -> str:
        value = value.strip()
        if not ENTITY_RE.match(value):
            raise ValueError("To nie wygląda na identyfikator encji Home Assistant.")
        return value


class TariffSummary(BaseModel):
    id: str
    name: str
    description: str
    preset_id: str | None = None
    is_preset: bool
    config: dict[str, Any]
    created_at: str
    updated_at: str
