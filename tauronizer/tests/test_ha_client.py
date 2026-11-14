from __future__ import annotations

import asyncio
from datetime import datetime, timezone

import pytest

from tauronizer.ha_client import ENERGY_UNITS, HAClient, HAError


class StubClient(HAClient):
    """HAClient with the WebSocket layer replaced by canned rows."""

    def __init__(self, rows: list[dict], unit: str = "kWh") -> None:
        super().__init__()
        self.rows = rows
        self.unit = unit

    async def _ws_call(self, payload, timeout: float = 60):
        entity_id = payload["statistic_ids"][0]
        return {entity_id: self.rows}

    async def get_statistics_metadata(self, entity_id: str):
        return {"unit_of_measurement": self.unit}

    async def close(self) -> None:
        await self._http.aclose()


def run(coro):
    return asyncio.run(coro)


def test_parse_start_supports_iso_seconds_and_milliseconds() -> None:
    from_iso = HAClient._parse_start("2026-01-05T09:00:00+00:00")
    assert from_iso == datetime(2026, 1, 5, 9, tzinfo=timezone.utc)

    seconds = HAClient._parse_start(1767603600)
    milliseconds = HAClient._parse_start(1767603600000)
    assert seconds == milliseconds == datetime(2026, 1, 5, 9, tzinfo=timezone.utc)

    assert HAClient._parse_start(None) is None
    assert HAClient._parse_start("not-a-date") is None
    assert HAClient._parse_start([1]) is None


def test_energy_unit_factors_cover_wh_and_mwh() -> None:
    assert ENERGY_UNITS["wh"] == pytest.approx(0.001)
    assert ENERGY_UNITS["kwh"] == 1.0
    assert ENERGY_UNITS["mwh"] == 1000.0


def test_statistics_are_converted_to_kwh_and_sorted() -> None:
    client = StubClient(
        rows=[
            {"start": "2026-01-05T10:00:00+00:00", "change": 500.0},
            {"start": "2026-01-05T09:00:00+00:00", "change": "250"},
            {"start": "2026-01-05T11:00:00+00:00", "change": None},
            {"start": "2026-01-05T12:00:00+00:00", "change": 1000.0},
        ],
        unit="Wh",
    )
    try:
        samples, unit = run(
            client.get_statistics(
                "sensor.energy",
                datetime(2026, 1, 5, tzinfo=timezone.utc),
                datetime(2026, 1, 6, tzinfo=timezone.utc),
            )
        )
    finally:
        run(client.close())

    assert unit == "Wh"
    assert [sample.kwh for sample in samples] == pytest.approx([0.25, 0.5, 1.0])
    assert samples[0].timestamp < samples[1].timestamp < samples[2].timestamp


def test_unknown_unit_is_treated_as_kwh() -> None:
    client = StubClient(
        rows=[{"start": "2026-01-05T10:00:00+00:00", "change": 2.5}],
        unit="kWh (dziwne)",
    )
    try:
        samples, _ = run(
            client.get_statistics(
                "sensor.energy",
                datetime(2026, 1, 5, tzinfo=timezone.utc),
                datetime(2026, 1, 6, tzinfo=timezone.utc),
            )
        )
    finally:
        run(client.close())

    assert samples[0].kwh == pytest.approx(2.5)


class MetadataFailureClient(StubClient):
    async def get_statistics_metadata(self, entity_id: str):
        raise HAError("brak metadanych")

    async def get_entity(self, entity_id: str):
        return {"attributes": {"unit_of_measurement": "Wh"}}


def test_statistics_fall_back_to_entity_unit() -> None:
    client = MetadataFailureClient(
        rows=[{"start": "2026-01-05T10:00:00+00:00", "change": 3000.0}],
        unit="kWh",
    )
    try:
        samples, unit = run(
            client.get_statistics(
                "sensor.energy",
                datetime(2026, 1, 5, tzinfo=timezone.utc),
                datetime(2026, 1, 6, tzinfo=timezone.utc),
            )
        )
    finally:
        run(client.close())

    assert unit == "Wh"
    assert samples[0].kwh == pytest.approx(3.0)
