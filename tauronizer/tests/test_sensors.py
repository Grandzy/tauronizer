from __future__ import annotations

import asyncio
import copy
import json
from datetime import datetime

import httpx
import pytest
from fastapi.testclient import TestClient

from tauronizer import db
from tauronizer.main import app
from tauronizer.ha_client import HAClient, HAError
from tauronizer.sensors import (SensorPublisher, zone_state, discovery,
                               DISCOVERY_TOPIC, STATE_TOPIC, AVAILABILITY_TOPIC)
from tauronizer.tariffs import PRESETS, TZ


class FakeMQTT:
    def __init__(self):
        self.messages = []
        self.fail = False

    async def publish_mqtt(self, topic, payload, *, retain):
        if self.fail:
            raise HAError('Broker offline')
        self.messages.append((topic, payload, retain))


@pytest.fixture
def sensor_client(tmp_path, monkeypatch):
    monkeypatch.setenv('DATA_DIR', str(tmp_path))
    with TestClient(app) as client:
        fake = FakeMQTT()
        app.state.sensors.ha = fake
        yield client, fake


def test_settings_persist_and_publish_discovery(sensor_client):
    client, fake = sensor_client
    assert client.get('/api/sensors').json()['tariff_id'] is None
    response = client.put('/api/sensors', json={'tariff_id': 'preset_g12'})
    assert response.status_code == 200
    data = response.json()
    assert data['status'] == 'published'
    assert data['published_state'] == data['current_zone']
    assert db.get_setting('sensor_tariff_id') == 'preset_g12'
    config = json.loads(next(payload for topic, payload, _ in fake.messages if topic == DISCOVERY_TOPIC))
    assert config['unique_id'] == 'tauronizer_strefa'
    assert config['default_entity_id'] == 'sensor.tauronizer_strefa'
    assert config['expire_after'] == 90
    assert config['availability_topic'] == AVAILABILITY_TOPIC
    assert any(topic == DISCOVERY_TOPIC and retained for topic, _, retained in fake.messages)
    assert all(not retained for topic, _, retained in fake.messages if topic == STATE_TOPIC)
    # Creating a fresh publisher after a restart reads the saved selection.
    assert SensorPublisher(fake).snapshot()['tariff_id'] == 'preset_g12'


def test_invalid_selection_does_not_overwrite_settings(sensor_client):
    client, fake = sensor_client
    client.put('/api/sensors', json={'tariff_id': 'preset_g12'})
    assert client.put('/api/sensors', json={'tariff_id': 'not-there'}).status_code == 404
    assert db.get_setting('sensor_tariff_id') == 'preset_g12'


def test_publish_failure_preserves_selection_and_recovers(sensor_client):
    client, fake = sensor_client
    fake.fail = True
    result = client.put('/api/sensors', json={'tariff_id': 'preset_g13'}).json()
    assert result['status'] == 'error'
    assert result['last_published'] is None
    assert db.get_setting('sensor_tariff_id') == 'preset_g13'
    fake.fail = False
    result = client.put('/api/sensors', json={'tariff_id': 'preset_g13'}).json()
    assert result['status'] == 'published'
    assert result['error'] is None


def test_disable_removes_retained_discovery(sensor_client):
    client, fake = sensor_client
    client.put('/api/sensors', json={'tariff_id': 'preset_g12'})
    result = client.put('/api/sensors', json={'tariff_id': None}).json()
    assert result['status'] == 'disabled'
    assert result['published_state'] is None
    assert (DISCOVERY_TOPIC, '', True) in fake.messages
    assert (AVAILABILITY_TOPIC, 'offline', False) in fake.messages


def test_deleted_tariff_does_not_leave_live_state(sensor_client):
    client, fake = sensor_client
    client.put('/api/sensors', json={'tariff_id': 'preset_g12'})
    db.delete_tariff('preset_g12')
    result = client.put('/api/sensors', json={'tariff_id': 'preset_g12'})
    assert result.status_code == 404
    asyncio.run(app.state.sensors.refresh())
    assert app.state.sensors.snapshot()['status'] == 'missing_tariff'
    assert (DISCOVERY_TOPIC, '', True) in fake.messages


@pytest.mark.parametrize('preset_id,when,expected', [
    ('g12', (2026, 1, 9, 17), 'Szczyt'),  # Friday, user example
    ('g12', (2026, 1, 9, 13), 'Pozostałe godziny — strefa domyślna'),
    ('g13', (2026, 1, 9, 16), 'Szczyt popołudniowy (zima)'),
    ('g13', (2026, 7, 10, 19), 'Szczyt popołudniowy (lato)'),
    ('g13', (2026, 7, 10, 22), 'Pozostałe godziny — strefa domyślna'),
    ('g13', (2026, 1, 6, 17), 'Pozostałe godziny — strefa domyślna'),
    ('g12w', (2026, 1, 10, 17), 'Pozostałe godziny — strefa domyślna'),
])
def test_sensor_uses_tariff_engine(preset_id, when, expected):
    tariff = copy.deepcopy(next(p for p in PRESETS if p['id'] == preset_id))
    assert zone_state(tariff, datetime(*when, tzinfo=TZ))['state'] == expected


def test_renamed_zone_is_published_verbatim():
    tariff = copy.deepcopy(next(p for p in PRESETS if p['id'] == 'g12'))
    tariff['config']['zones'][0]['name'] = 'Moja droga strefa'
    assert zone_state(tariff, datetime(2026, 1, 9, 17, tzinfo=TZ))['state'] == 'Moja droga strefa'


def test_ha_mqtt_action_request(monkeypatch):
    monkeypatch.setenv('HA_TOKEN', 'test-token')
    async def scenario():
        ha = HAClient()
        await ha._http.aclose()
        requests = []
        def handler(request):
            requests.append(request)
            return httpx.Response(200, json=[])
        ha._http = httpx.AsyncClient(transport=httpx.MockTransport(handler))
        await ha.publish_mqtt(STATE_TOPIC, 'Szczyt', retain=False)
        assert requests[0].url.path == '/api/services/mqtt/publish'
        assert json.loads(requests[0].content) == {
            'topic': STATE_TOPIC, 'payload': 'Szczyt', 'qos': 1, 'retain': False}
        await ha.close()
    asyncio.run(scenario())


def test_worker_runs_and_wakes_without_open_browser(tmp_path, monkeypatch):
    monkeypatch.setenv('DATA_DIR', str(tmp_path))
    db.init_db()
    db.set_setting('sensor_tariff_id', 'preset_g12')
    async def scenario():
        notified = asyncio.Event()
        class ObservableMQTT(FakeMQTT):
            async def publish_mqtt(self, topic, payload, *, retain):
                await super().publish_mqtt(topic, payload, retain=retain)
                if topic == AVAILABILITY_TOPIC and payload == 'online':
                    notified.set()
        fake = ObservableMQTT()
        publisher = SensorPublisher(fake)
        task = asyncio.create_task(publisher.run())
        try:
            await asyncio.wait_for(notified.wait(), timeout=2)
            assert publisher.status == 'published'
            notified.clear()
            tariff = db.get_tariff('preset_g12')
            for zone in tariff['config']['zones']:
                zone['name'] = 'Nowa nazwa'
            db.update_tariff(tariff['id'], tariff['name'], tariff['description'], tariff['config'])
            publisher.wake.set()
            await asyncio.wait_for(notified.wait(), timeout=2)
            assert publisher.published_state == 'Nowa nazwa'
        finally:
            task.cancel()
            try:
                await task
            except asyncio.CancelledError:
                pass
    asyncio.run(scenario())


def test_price_includes_every_variable_fee_and_excise_but_no_monthly_fees():
    from tauronizer.sensors import price_state
    tariff = copy.deepcopy(next(p for p in PRESETS if p['id'] == 'g12'))
    when = datetime(2026, 1, 9, 17, tzinfo=TZ)
    assert price_state(tariff, 'net', when)['state'] == pytest.approx(0.8756)
    assert price_state(tariff, 'gross', when)['state'] == pytest.approx(1.076988)
    tariff['config']['variable_fees'].append({'name': 'Moja opłata', 'net_per_kwh': 0.01})
    tariff['config']['fixed_fees'].append({'name': 'Stała', 'net_monthly': 10000})
    assert price_state(tariff, 'net', when)['state'] == pytest.approx(0.8856)
    assert price_state(tariff, 'gross', when)['state'] == pytest.approx(1.089288)
    tariff['config']['vat_percent'] = 0
    assert price_state(tariff, 'gross', when)['state'] == price_state(tariff, 'net', when)['state']


def test_price_changes_with_zone_and_uses_configured_vat():
    from tauronizer.sensors import price_state
    tariff = copy.deepcopy(next(p for p in PRESETS if p['id'] == 'g12'))
    peak = price_state(tariff, 'net', datetime(2026, 1, 9, 17, tzinfo=TZ))
    offpeak = price_state(tariff, 'net', datetime(2026, 1, 9, 22, tzinfo=TZ))
    assert peak['state'] > offpeak['state']
    assert offpeak['state'] == pytest.approx(0.5173)
    tariff['config']['vat_percent'] = 8
    assert price_state(tariff, 'gross', datetime(2026, 1, 9, 22, tzinfo=TZ))['state'] == pytest.approx(0.558684)


def test_price_sensor_publishes_numeric_state_and_persists_mode(sensor_client):
    from tauronizer.sensors import PRICE_DISCOVERY_TOPIC, PRICE_STATE_TOPIC
    client, fake = sensor_client
    result = client.put('/api/sensors', json={'tariff_id': 'preset_g12', 'price_mode': 'net'}).json()
    assert result['price_entity_id'] == 'sensor.tauronizer_cena_kwh'
    assert result['price_mode'] == result['published_price_mode'] == 'net'
    assert db.get_setting('sensor_price_mode') == 'net'
    assert SensorPublisher(fake).snapshot()['price_mode'] == 'net'
    config = json.loads(next(payload for topic, payload, _ in fake.messages if topic == PRICE_DISCOVERY_TOPIC))
    assert config['default_entity_id'] == 'sensor.tauronizer_cena_kwh'
    assert config['unit_of_measurement'] == 'PLN/kWh'
    assert config['state_class'] == 'measurement'
    assert config['expire_after'] == 90
    messages = [json.loads(payload) for topic, payload, _ in fake.messages if topic == PRICE_STATE_TOPIC]
    assert isinstance(messages[-1]['state'], (float, int))
    assert messages[-1]['attributes']['price_mode'] == 'net'
    assert all(not retained for topic, _, retained in fake.messages if topic == PRICE_STATE_TOPIC)
    # Older clients not sending mode must not reset an existing preference.
    result = client.put('/api/sensors', json={'tariff_id': 'preset_g12'}).json()
    assert result['price_mode'] == 'net'
    gross = client.put('/api/sensors', json={'tariff_id': 'preset_g12', 'price_mode': 'gross'}).json()
    assert gross['published_price_mode'] == 'gross'
    assert gross['published_price'] == pytest.approx(round(result['published_price'] * 1.23, 6))
    client.put('/api/sensors', json={'tariff_id': None})
    assert (PRICE_DISCOVERY_TOPIC, '', True) in fake.messages


def test_price_mode_rejects_invalid_value_without_overwriting_settings(sensor_client):
    client, _ = sensor_client
    assert client.put('/api/sensors', json={'tariff_id': 'preset_g12', 'price_mode': 'net'}).status_code == 200
    result = client.put('/api/sensors', json={'tariff_id': 'preset_g13', 'price_mode': 'invalid'})
    assert result.status_code == 422
    assert db.get_setting('sensor_price_mode') == 'net'
    assert db.get_setting('sensor_tariff_id') == 'preset_g12'


def test_failed_mode_change_preserves_last_published_price_label(sensor_client):
    client, fake = sensor_client
    old = client.put('/api/sensors', json={'tariff_id': 'preset_g12', 'price_mode': 'gross'}).json()
    fake.fail = True
    result = client.put('/api/sensors', json={'tariff_id': 'preset_g12', 'price_mode': 'net'}).json()
    assert result['status'] == 'error'
    assert result['price_mode'] == 'net'
    assert result['published_price_mode'] == 'gross'
    assert result['published_price'] == old['published_price']


@pytest.mark.parametrize('preset_id', ['g11', 'g12', 'g12w', 'g13'])
def test_sensor_variable_price_matches_analysis(preset_id):
    from tauronizer.sensors import price_state
    from tauronizer.calc import analyze, ConsumptionSample
    tariff = copy.deepcopy(next(p for p in PRESETS if p['id'] == preset_id))
    tariff['config']['fixed_fees'] = []
    tariff['config']['capacity_fee'] = None
    when = datetime(2026, 1, 9, 17, tzinfo=TZ)
    amount = 10000
    result = analyze([tariff], [ConsumptionSample(timestamp=when, kwh=amount)], when.date(), when.date())['tariffs'][0]
    assert result['error'] is None
    assert price_state(tariff, 'net', when)['state'] == pytest.approx(result['breakdown']['net_pln'] / amount)
    assert price_state(tariff, 'gross', when)['state'] == pytest.approx(result['total_pln'] / amount)
