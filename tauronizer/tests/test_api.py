from __future__ import annotations

from datetime import date, datetime, timezone

import pytest
from fastapi.testclient import TestClient

from tauronizer.calc import ConsumptionSample
from tauronizer.ha_client import HAError
from tauronizer.main import app
from tauronizer.tariffs import TZ


class FakeHA:
    is_supervisor = True

    def __init__(self, samples: list[ConsumptionSample] | None = None) -> None:
        self.samples = samples if samples is not None else []

    async def get_entity(self, entity_id: str):
        return {
            "entity_id": entity_id,
            "state": "100.0",
            "attributes": {
                "friendly_name": "Energia domu",
                "unit_of_measurement": "kWh",
                "device_class": "energy",
                "state_class": "total_increasing",
            },
        }

    async def get_statistics(self, entity_id, start, end):
        return self.samples, "kWh"

    async def close(self):
        pass


@pytest.fixture
def client(tmp_path, monkeypatch):
    monkeypatch.setenv("DATA_DIR", str(tmp_path))
    with TestClient(app) as test_client:
        yield test_client


def make_samples() -> list[ConsumptionSample]:
    day = date(2026, 1, 5)
    hours = [(10, 2.0), (20, 2.0), (3, 4.0)]
    return [
        ConsumptionSample(
            timestamp=datetime(day.year, day.month, day.day, hour, tzinfo=TZ).astimezone(
                timezone.utc
            ),
            kwh=kwh,
        )
        for hour, kwh in hours
    ]


def test_presets_are_seeded(client: TestClient) -> None:
    response = client.get("/api/tariffs")
    assert response.status_code == 200
    tariffs = response.json()["tariffs"]
    assert {item["preset_id"] for item in tariffs} == {"g11", "g12", "g12w", "g13", "g14dynamic"}
    assert all(item["is_preset"] for item in tariffs)


def test_tariff_crud(client: TestClient) -> None:
    base = client.get("/api/tariffs").json()["tariffs"][0]

    created = client.post(
        "/api/tariffs",
        json={
            "name": "Moja taryfa",
            "description": "Test",
            "config": base["config"],
        },
    )
    assert created.status_code == 201, created.text
    tariff = created.json()
    assert tariff["name"] == "Moja taryfa"
    assert tariff["is_preset"] is False

    updated = client.put(
        f"/api/tariffs/{tariff['id']}",
        json={
            "name": "Moja taryfa 2",
            "description": "Po zmianie",
            "config": base["config"],
        },
    )
    assert updated.status_code == 200
    assert updated.json()["name"] == "Moja taryfa 2"

    duplicated = client.post(f"/api/tariffs/{tariff['id']}/duplicate")
    assert duplicated.status_code == 201
    assert duplicated.json()["name"] == "Moja taryfa 2 (kopia)"

    deleted = client.delete(f"/api/tariffs/{duplicated.json()['id']}")
    assert deleted.status_code == 200
    assert deleted.json()["deleted"] is True

    missing = client.delete("/api/tariffs/does-not-exist")
    assert missing.status_code == 404


def test_invalid_tariff_is_rejected(client: TestClient) -> None:
    response = client.post(
        "/api/tariffs",
        json={
            "name": "Dziura",
            "description": "",
            "config": {
                "zones": [
                    {
                        "id": "peak",
                        "name": "Szczyt",
                        "days": [0, 1, 2, 3, 4],
                        "intervals": ["06:00-22:00"],
                        "energy_net": 0.5,
                        "distribution_net": 0.3,
                    }
                ],
                "fixed_fees": [],
                "variable_fees": [],
            },
        },
    )
    assert response.status_code == 400
    assert "nie pokrywa" in response.json()["detail"]


def test_restore_presets(client: TestClient) -> None:
    preset = client.get("/api/tariffs").json()["tariffs"][0]
    assert client.delete(f"/api/tariffs/{preset['id']}").status_code == 200

    response = client.post("/api/tariffs/restore-presets")
    assert response.status_code == 200
    assert response.json()["restored"] == 5

    tariffs = client.get("/api/tariffs").json()["tariffs"]
    assert len(tariffs) == 5


def test_analyze_and_history(client: TestClient) -> None:
    client.app.state.ha = FakeHA(make_samples())
    response = client.post(
        "/api/analyze",
        json={
            "entity_id": "sensor.energia_dom",
            "start": "2026-01-05",
            "end": "2026-01-05",
            "tariff_ids": [],
        },
    )
    assert response.status_code == 200, response.text
    result = response.json()
    assert result["total_kwh"] == 8.0
    assert result["entity_name"] == "Energia domu"
    assert result["cheapest_tariff_id"]
    assert result["id"]
    assert result["data_quality"]["received_hours"] == 3
    assert result["data_quality"]["missing_hours"] == 21
    assert any("Koszty mogą być zaniżone" in warning for warning in result["warnings"])
    assert len(result["tariffs"]) == 5

    history = client.get("/api/analyses").json()["analyses"]
    assert len(history) == 1
    assert history[0]["id"] == result["id"]
    assert history[0]["cheapest_name"]

    detail = client.get(f"/api/analyses/{result['id']}")
    assert detail.status_code == 200
    assert detail.json()["result"]["total_kwh"] == 8.0
    assert detail.json()["result"]["data_quality"] == result["data_quality"]

    assert client.delete(f"/api/analyses/{result['id']}").status_code == 200
    assert client.get("/api/analyses").json()["analyses"] == []


def test_invoice_analysis_uses_shared_tariff_calculation(client: TestClient) -> None:
    response = client.post("/api/analyze", json={
        "source": "invoice", "total_kwh": 240,
        "start": "2026-01-05", "end": "2026-01-05",
        "tariff_ids": ["preset_g11"],
    })
    assert response.status_code == 200, response.text
    result = response.json()
    assert result["total_kwh"] == 240
    assert result["data_source"] == "invoice"
    assert result["estimated_profile"] is True
    assert result["data_quality"] is None
    assert result["sample_count"] == 24
    assert "równomiernie" in result["warnings"][0]
    assert result["tariffs"][0]["total_pln"] is not None


def test_invoice_analysis_rejects_missing_or_invalid_consumption(client: TestClient) -> None:
    missing = client.post("/api/analyze", json={
        "source": "invoice", "start": "2026-01-05", "end": "2026-01-05",
    })
    assert missing.status_code == 400
    assert "kWh" in missing.json()["detail"]

    negative = client.post("/api/analyze", json={
        "source": "invoice", "total_kwh": -2,
        "start": "2026-01-05", "end": "2026-01-05",
    })
    assert negative.status_code == 422
    assert "większe od zera" in negative.json()["detail"][0]["msg"]

    reversed_period = client.post("/api/analyze", json={
        "source": "invoice", "total_kwh": 20,
        "start": "2026-01-06", "end": "2026-01-05",
    })
    assert reversed_period.status_code == 400


def test_analyze_rejects_future_and_reversed_ranges(client: TestClient) -> None:
    client.app.state.ha = FakeHA(make_samples())
    reversed_range = client.post(
        "/api/analyze",
        json={
            "entity_id": "sensor.energia_dom",
            "start": "2026-01-06",
            "end": "2026-01-05",
        },
    )
    assert reversed_range.status_code == 400

    future = client.post(
        "/api/analyze",
        json={
            "entity_id": "sensor.energia_dom",
            "start": "2026-01-05",
            "end": "2099-01-01",
        },
    )
    assert future.status_code == 400


def test_analyze_without_statistics(client: TestClient) -> None:
    client.app.state.ha = FakeHA([])
    response = client.post(
        "/api/analyze",
        json={
            "entity_id": "sensor.energia_dom",
            "start": "2026-01-05",
            "end": "2026-01-05",
        },
    )
    assert response.status_code == 400
    assert "statystyk" in response.json()["detail"]


def test_analyze_unknown_entity(client: TestClient) -> None:
    class BrokenHA(FakeHA):
        async def get_entity(self, entity_id: str):
            raise HAError("Nie znaleziono encji")

    client.app.state.ha = BrokenHA()
    response = client.post(
        "/api/analyze",
        json={
            "entity_id": "sensor.nie_ma",
            "start": "2026-01-05",
            "end": "2026-01-05",
        },
    )
    assert response.status_code == 400
    assert "Nie znaleziono" in response.json()["detail"]


def test_index_and_health(client: TestClient) -> None:
    assert client.get("/health").json()["status"] == "ok"
    index = client.get("/")
    assert index.status_code == 200
    assert "Tauronizer" in index.text


def test_capacity_configuration_roundtrip(client):
    base = client.get('/api/tariffs').json()['tariffs'][0]
    base['config']['capacity_fee'] = {
        'annual_kwh': 1200,
        'net_monthly_rates': [4.29, 10.31, 17.18, 24.05],
    }
    response = client.post('/api/tariffs', json={'name': 'Mocowa', 'config': base['config']})
    assert response.status_code == 201
    saved = response.json()
    assert saved['config']['capacity_fee'] == base['config']['capacity_fee']
    client.app.state.ha = FakeHA(make_samples())
    result = client.post('/api/analyze', json={
        'entity_id': 'sensor.energia_dom', 'start': '2026-01-05', 'end': '2026-01-05',
        'tariff_ids': [saved['id']],
    }).json()
    fee = result['tariffs'][0]['capacity_fee']
    assert fee['net_monthly'] == 10.31
    assert fee['estimated'] is False
    stored = client.get(f"/api/analyses/{result['id']}").json()['result']
    assert stored['tariffs'][0]['capacity_fee'] == fee


@pytest.mark.parametrize('capacity', [
    {'annual_kwh': -1},
    {'net_monthly_rates': [1, 2, 3]},
    {'net_monthly_rates': [1, 2, 3, 4, 5]},
    {'net_monthly_rates': [1, -2, 3, 4]},
    {'net_monthly_rates': [1, 2, 3, 10001]},
])
def test_invalid_capacity_fee_is_rejected(client, capacity):
    base = client.get('/api/tariffs').json()['tariffs'][0]
    base['config']['capacity_fee'] = capacity
    response = client.post('/api/tariffs', json={'name': 'Zła', 'config': base['config']})
    assert response.status_code == 422


def test_legacy_config_without_capacity_is_still_accepted(client):
    base = client.get('/api/tariffs').json()['tariffs'][0]
    del base['config']['capacity_fee']
    response = client.post('/api/tariffs', json={'name': 'Starsza taryfa', 'config': base['config']})
    assert response.status_code == 201
    assert response.json()['config']['capacity_fee'] is None


def test_default_zone_is_saved_last_and_cannot_be_duplicated(client: TestClient) -> None:
    import copy
    from tauronizer.tariffs import PRESETS
    config = copy.deepcopy(next(p for p in PRESETS if p['id'] == 'g13')['config'])
    config['zones'].insert(0, config['zones'].pop())
    response = client.post('/api/tariffs', json={'name': 'Default safety', 'config': config})
    assert response.status_code == 201, response.text
    saved = response.json()
    assert saved['config']['zones'][-1]['id'] == 'pozaszczyt'
    assert saved['config']['zones'][-1]['is_default'] is True
    assert client.get('/api/tariffs').status_code == 200
    config['zones'][1]['is_default'] = True
    rejected = client.post('/api/tariffs', json={'name': 'Two defaults', 'config': config})
    assert rejected.status_code == 400
    assert 'tylko jedną' in rejected.json()['detail']


def test_monthly_comparison_uses_sensor_tariff_and_preserves_history_snapshot(client):
    from tauronizer.db import set_setting
    tariffs = client.get('/api/tariffs').json()['tariffs']
    current = next(t for t in tariffs if t['preset_id'] == 'g11')
    other = next(t for t in tariffs if t['preset_id'] == 'g12')
    set_setting('sensor_tariff_id', current['id'])
    client.app.state.ha = FakeHA(make_samples())
    result = client.post('/api/analyze', json={
        'entity_id': 'sensor.energia_dom', 'start': '2026-01-05', 'end': '2026-01-05',
        'tariff_ids': [other['id']],
    }).json()
    assert result['current_tariff_id'] == current['id']
    assert [t['tariff_id'] for t in result['tariffs']] == [other['id']]
    assert result['monthly_costs'][0]['current']['tariff_id'] == current['id']
    assert result['monthly_costs'][0]['current']['total_pln'] > 0
    set_setting('sensor_tariff_id', other['id'])
    stored = client.get(f"/api/analyses/{result['id']}").json()['result']
    assert stored['monthly_costs'] == result['monthly_costs']
    assert stored['current_tariff_id'] == current['id']


def test_analysis_reports_full_coverage_without_warning(client):
    from datetime import timedelta
    start = datetime(2026,1,9,tzinfo=TZ).astimezone(timezone.utc)
    client.app.state.ha = FakeHA([ConsumptionSample(start+timedelta(hours=i),0) for i in range(24)])
    result = client.post('/api/analyze',json={'entity_id':'sensor.energia_dom','start':'2026-01-09','end':'2026-01-09','tariff_ids':['preset_g11']}).json()
    assert result['data_quality']['percent']==100
    assert result['data_quality']['missing_hours']==0
    assert result['warnings']==[]


def test_schedule_endpoint_previews_dynamic_tariff_when_current_is_static(client,monkeypatch):
    from tauronizer.db import set_setting, save_kompas
    from tauronizer.forecast import dynamic_schedule
    import tauronizer.main as main
    now=datetime(2026,1,9,17,30,tzinfo=TZ)
    for hour,level in [(17,0),(18,2)]:
        stamp=datetime(2026,1,9,hour,tzinfo=TZ).astimezone(timezone.utc)
        save_kompas([{'utc_hour':stamp.isoformat(),'business_date':'2026-01-09','level':level,'publication_utc':stamp.isoformat()}])
    monkeypatch.setattr(main,'dynamic_schedule',lambda t:dynamic_schedule(t,now))
    set_setting('sensor_tariff_id','preset_g11')
    response=client.get('/api/kompas/schedule')
    assert response.status_code==200
    result=response.json()
    assert result['tariff_id']=='preset_g14dynamic'
    assert result['is_current_tariff'] is False
    assert result['next_change']['level']==2
    set_setting('sensor_tariff_id','preset_g14dynamic')
    assert client.get('/api/kompas/schedule').json()['is_current_tariff'] is True


def test_analysis_deduplicates_hours_and_preserves_raw_quality(client):
    stamp=datetime(2026,1,9,10,tzinfo=TZ).astimezone(timezone.utc)
    client.app.state.ha=FakeHA([ConsumptionSample(stamp,1),ConsumptionSample(stamp,2),
                              ConsumptionSample(stamp.replace(hour=11),float('nan')),
                              ConsumptionSample(stamp.replace(hour=12),-1)])
    result=client.post('/api/analyze',json={'entity_id':'sensor.energia_dom','start':'2026-01-09','end':'2026-01-09','tariff_ids':['preset_g11']}).json()
    assert result['total_kwh']==2
    assert result['data_quality']['received_hours']==1
    assert result['data_quality']['invalid_samples']==2
    assert result['data_quality']['duplicate_samples']==1
    assert result['data_quality']['missing_hours']==23
    assert any('ostatni prawidłowy' in warning for warning in result['warnings'])
