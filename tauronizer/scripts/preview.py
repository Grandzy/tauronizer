"""Local preview with deterministic demo data. Not part of the shipped app.

Usage (from the repository root):
    python tauronizer/scripts/preview.py
    open http://127.0.0.1:8099
"""

from __future__ import annotations

import asyncio
import math
import os
import random
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "app"))
os.environ.setdefault("DATA_DIR", str(ROOT / "data-preview"))
os.environ.setdefault("KOMPAS_AUTO_SYNC", "0")
os.environ.setdefault("EXPORT_PRICES_AUTO_SYNC", "0")
os.environ.setdefault("PURCHASE_PRICES_AUTO_SYNC", "0")

import uvicorn  # noqa: E402

from tauronizer.calc import ConsumptionSample  # noqa: E402
from tauronizer.main import app  # noqa: E402
from tauronizer.tariffs import TZ  # noqa: E402

ENTITIES = [
    {"entity_id": "sensor.eksport_siec", "name": "Eksport do sieci", "unit": "kWh",
     "state_class": "total_increasing", "device_class": "energy", "state": "4120.2", "available": True},
    {
        "entity_id": "sensor.energia_dom",
        "name": "Energia domu",
        "unit": "kWh",
        "state_class": "total_increasing",
        "device_class": "energy",
        "state": "12450.4",
        "available": True,
    },
    {
        "entity_id": "sensor.energia_dom_wh",
        "name": "Energia domu (Wh)",
        "unit": "Wh",
        "state_class": "total_increasing",
        "device_class": "energy",
        "state": "12450400",
        "available": True,
    },
    {
        "entity_id": "sensor.pompa_ciepla",
        "name": "Pompa ciepła",
        "unit": "kWh",
        "state_class": "total_increasing",
        "device_class": "energy",
        "state": "3120.9",
        "available": True,
    },
]


class DemoHA:
    is_supervisor = True

    async def get_energy_entities(self):
        return ENTITIES

    async def get_entity(self, entity_id):
        for entity in ENTITIES:
            if entity["entity_id"] == entity_id:
                return {
                    "entity_id": entity_id,
                    "state": entity["state"],
                    "attributes": {
                        "friendly_name": entity["name"],
                        "unit_of_measurement": entity["unit"],
                        "springs": None,
                        "device_class": "energy",
                        "state_class": "total_increasing",
                    },
                }
        raise ValueError("unknown entity")

    async def get_statistics(self, entity_id, start, end):
        samples = demo_samples(start, end)
        if entity_id == 'sensor.eksport_siec':
            samples = [ConsumptionSample(s.timestamp, round(max(0, 2.5 * math.sin((s.timestamp.astimezone(TZ).hour-7)*math.pi/12)),4)
                       if 7 <= s.timestamp.astimezone(TZ).hour <= 19 else 0) for s in samples]
        return samples, "kWh"

    async def publish_mqtt(self, topic, payload, *, retain):
        # Demo only: no connection to a real broker or Home Assistant.
        pass

    async def close(self):
        pass


def demo_samples(start: datetime, end: datetime) -> list[ConsumptionSample]:
    samples: list[ConsumptionSample] = []
    cursor = start.replace(minute=0, second=0, microsecond=0)
    if cursor < start:
        cursor += timedelta(hours=1)
    while cursor < end:
        local = cursor.astimezone(TZ)
        hour = local.hour
        weekday = local.weekday()
        base = 0.26
        if 6 <= hour < 9:
            base += 0.42
        if 17 <= hour < 22:
            base += 0.86
        if weekday >= 5:
            base += 0.14
            if 11 <= hour < 16:
                base += 0.35
        base += 0.13 * math.sin((hour + weekday) / 3.2) + 0.07
        season = 1.24 if local.month in (12, 1, 2) else (0.84 if local.month in (6, 7, 8) else 1.0)
        noise = random.Random(cursor.toordinal() * 31 + hour).uniform(-0.07, 0.09)
        kwh = max(0.04, (base + noise) * season)
        samples.append(ConsumptionSample(timestamp=cursor.astimezone(timezone.utc), kwh=round(kwh, 4)))
        cursor += timedelta(hours=1)
    return samples


async def main() -> None:
    server = uvicorn.Server(
        uvicorn.Config(app, host="127.0.0.1", port=8099, log_level="warning")
    )
    serve_task = asyncio.create_task(server.serve())
    while not server.started:
        await asyncio.sleep(0.05)
    original_ha = app.state.ha
    app.state.ha = DemoHA()
    app.state.sensors.ha = app.state.ha
    await original_ha.close()
    print("Tauronizer preview: http://127.0.0.1:8099")
    await serve_task


if __name__ == "__main__":
    asyncio.run(main())
