"""Current tariff zone published through Home Assistant's MQTT integration."""
from __future__ import annotations

import asyncio
import json
import logging
from datetime import datetime
from typing import Any

from . import __version__
from .db import get_setting, set_setting, get_tariff, utcnow
from .tariffs import TZ, TariffValidationError, compile_zones, holidays_between, zone_for

_LOGGER = logging.getLogger(__name__)
DISCOVERY_TOPIC = 'homeassistant/sensor/tauronizer/strefa/config'
STATE_TOPIC = 'tauronizer/strefa/state'
AVAILABILITY_TOPIC = 'tauronizer/strefa/availability'
ENTITY_ID = 'sensor.tauronizer_strefa'
PRICE_ENTITY_ID = 'sensor.tauronizer_cena_kwh'
PRICE_DISCOVERY_TOPIC = 'homeassistant/sensor/tauronizer/cena_kwh/config'
PRICE_STATE_TOPIC = 'tauronizer/cena_kwh/state'


def zone_state(tariff: dict[str, Any], now: datetime | None = None) -> dict[str, Any]:
    local = (now or datetime.now(TZ)).astimezone(TZ)
    zone = zone_for(local, compile_zones(tariff['config']),
                    holidays_between(local.date(), local.date()))
    return {'state': zone.name, 'attributes': {
        'tariff_id': tariff['id'], 'tariff_name': tariff['name'], 'zone_id': zone.id,
    }}


def price_state(tariff: dict[str, Any], mode: str = 'gross',
                now: datetime | None = None) -> dict[str, Any]:
    if mode not in ('net', 'gross'):
        raise ValueError('Nieprawidłowy tryb ceny.')
    local = (now or datetime.now(TZ)).astimezone(TZ)
    config = tariff['config']
    zone = zone_for(local, compile_zones(config), holidays_between(local.date(), local.date()))
    variable_rate = sum(float(fee.get('net_per_kwh', 0) or 0)
                        for fee in config.get('variable_fees') or [])
    excise = float(config.get('excise_net_per_kwh', 0) or 0)
    vat = float(config.get('vat_percent', 23) or 0)
    net = zone.energy_net + zone.distribution_net + variable_rate + excise
    gross = net * (1 + vat / 100)
    return {'state': round(gross if mode == 'gross' else net, 6), 'attributes': {
        'tariff_id': tariff['id'], 'tariff_name': tariff['name'],
        'zone_id': zone.id, 'zone_name': zone.name, 'price_mode': mode,
        'energy_net': zone.energy_net, 'distribution_net': zone.distribution_net,
        'variable_fees_net': round(variable_rate, 6), 'excise_net': excise,
        'vat_percent': vat,
    }}


def price_discovery() -> dict[str, Any]:
    result = discovery()
    result.update(name='Cena kWh', object_id='tauronizer_cena_kwh',
                  default_entity_id=PRICE_ENTITY_ID, unique_id='tauronizer_cena_kwh',
                  state_topic=PRICE_STATE_TOPIC, json_attributes_topic=PRICE_STATE_TOPIC,
                  unit_of_measurement='PLN/kWh', state_class='measurement',
                  suggested_display_precision=4, icon='mdi:cash')
    return result


def discovery() -> dict[str, Any]:
    return {
        'name': 'Strefa', 'object_id': 'tauronizer_strefa',
        'default_entity_id': ENTITY_ID, 'unique_id': 'tauronizer_strefa',
        'state_topic': STATE_TOPIC, 'value_template': '{{ value_json.state }}',
        'json_attributes_topic': STATE_TOPIC,
        'json_attributes_template': '{{ value_json.attributes | tojson }}',
        'availability_topic': AVAILABILITY_TOPIC,
        'expire_after': 90, 'icon': 'mdi:clock-outline',
        'device': {'identifiers': ['tauronizer'], 'name': 'Tauronizer',
                   'manufacturer': 'Tauronizer', 'sw_version': __version__},
        'origin': {'name': 'Tauronizer', 'sw_version': __version__,
                   'support_url': 'https://github.com/direk/tauronizer'},
    }


class SensorPublisher:
    def __init__(self, ha):
        self.ha = ha
        self.wake = asyncio.Event()
        self.lock = asyncio.Lock()
        self.last_published: str | None = None
        self.published_state: str | None = None
        self.published_price: float | None = None
        self.published_price_mode: str | None = None
        self.error: str | None = None
        self.status = 'disabled'

    def snapshot(self) -> dict[str, Any]:
        selected = get_setting('sensor_tariff_id')
        tariff = get_tariff(selected) if selected else None
        current = None
        current_price = None
        mode = get_setting('sensor_price_mode') or 'gross'
        if tariff:
            try:
                now = datetime.now(TZ)
                current = zone_state(tariff, now)['state']
                current_price = price_state(tariff, mode, now)['state']
            except ValueError:
                pass
        return {'tariff_id': selected, 'tariff_name': tariff['name'] if tariff else None,
                'entity_id': ENTITY_ID, 'current_zone': current,
                'status': self.status, 'error': self.error,
                'published_state': self.published_state, 'last_published': self.last_published,
                'state_topic': STATE_TOPIC, 'discovery_topic': DISCOVERY_TOPIC,
                'price_entity_id': PRICE_ENTITY_ID, 'price_mode': mode,
                'current_price': current_price, 'published_price': self.published_price,
                'published_price_mode': self.published_price_mode}

    async def refresh(self) -> None:
        async with self.lock:
            selected = get_setting('sensor_tariff_id')
            tariff = get_tariff(selected) if selected else None
            try:
                if not tariff:
                    if get_setting('sensor_discovered') == '1':
                        await self.ha.publish_mqtt(AVAILABILITY_TOPIC, 'offline', retain=False)
                        await self.ha.publish_mqtt(DISCOVERY_TOPIC, '', retain=True)
                        await self.ha.publish_mqtt(PRICE_DISCOVERY_TOPIC, '', retain=True)
                        set_setting('sensor_discovered', '0')
                    self.status = 'missing_tariff' if selected else 'disabled'
                    self.error = 'Wybrana taryfa została usunięta. Wybierz inną.' if selected else None
                    self.published_state = None
                    self.published_price = self.published_price_mode = None
                    return
                now = datetime.now(TZ)
                payload = zone_state(tariff, now)
                mode = get_setting('sensor_price_mode') or 'gross'
                price = price_state(tariff, mode, now)
                # Reannounce discovery on every heartbeat, including after an HA/MQTT restart.
                # Only discovery is retained: an old zone must not reappear after a restart.
                await self.ha.publish_mqtt(DISCOVERY_TOPIC, json.dumps(discovery(), ensure_ascii=False), retain=True)
                set_setting('sensor_discovered', '1')
                await self.ha.publish_mqtt(PRICE_DISCOVERY_TOPIC, json.dumps(price_discovery(), ensure_ascii=False), retain=True)
                await self.ha.publish_mqtt(STATE_TOPIC, json.dumps(payload, ensure_ascii=False), retain=False)
                await self.ha.publish_mqtt(PRICE_STATE_TOPIC, json.dumps(price, ensure_ascii=False), retain=False)
                await self.ha.publish_mqtt(AVAILABILITY_TOPIC, 'online', retain=False)
                self.last_published = utcnow()
                self.published_state = payload['state']
                self.published_price = price['state']
                self.published_price_mode = mode
                self.status, self.error = 'published', None
            except TariffValidationError as exc:
                self.status, self.error = 'waiting_data', str(exc)
            except Exception:
                self.status = 'error'
                self.error = 'Publikacja MQTT nie powiodła się. Sprawdź połączenie z Home Assistant, integrację MQTT i broker.'
                _LOGGER.warning('Tariff-sensor MQTT publication failed; retrying automatically.')

    async def run(self) -> None:
        while True:
            self.wake.clear()
            await self.refresh()
            now = datetime.now(TZ)
            # All tariff boundaries are full hours. Wake at the boundary, not 30 s later.
            delay = min(30.0, 3600 - (now.minute * 60 + now.second + now.microsecond / 1_000_000))
            try:
                await asyncio.wait_for(self.wake.wait(), timeout=max(0.05, delay))
            except TimeoutError:
                pass

    async def stop(self) -> None:
        if get_setting('sensor_discovered') == '1':
            try:
                await self.ha.publish_mqtt(AVAILABILITY_TOPIC, 'offline', retain=False)
            except Exception:
                pass  # expire_after also protects against a lost shutdown message.
