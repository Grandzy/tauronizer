from __future__ import annotations
import asyncio
import copy
from datetime import datetime, date, timezone
import httpx
import pytest
from tauronizer import db
from tauronizer.kompas import KompasCache, parse_rows, utc_key
from tauronizer.tariffs import PRESETS, compile_zones, zone_for, TZ, TariffValidationError
from tauronizer.calc import analyze, ConsumptionSample
from tauronizer.sensors import zone_state, price_state


def raw(instant='2026-01-09 16:00', level=0, day='2026-01-09', pub='2026-01-08 15:00:00'):
    return {'is_active': True, 'dtime_utc': instant, 'usage_fcst': level,
            'business_date': day, 'publication_ts_utc': pub}


@pytest.fixture
def database(tmp_path, monkeypatch):
    monkeypatch.setenv('DATA_DIR', str(tmp_path))
    db.init_db()
    return tmp_path


def g14():
    return copy.deepcopy(next(item for item in PRESETS if item['id'] == 'g14dynamic'))


def test_levels_and_atomic_unknown_level_rejection(database):
    rows=[raw(f'2026-01-09 {hour:02d}:00', hour-16) for hour in range(16,20)]
    db.save_kompas(parse_rows({'value': rows}))
    zones=compile_zones(g14()['config'])
    for hour in range(17,21):
        assert zone_for(datetime(2026,1,9,hour,tzinfo=TZ),zones,set()).kompas_level == hour-17
    with pytest.raises(ValueError): parse_rows({'value': [raw(level=4)]})
    with pytest.raises(ValueError): parse_rows({'value': [raw(level=True)]})
    with pytest.raises(ValueError): parse_rows({'value': [raw(day='2026-01-10')]})


def test_dst_repeated_hour_is_distinguished_in_utc(database):
    db.save_kompas(parse_rows({'value': [raw('2026-10-25 00:00',0,'2026-10-25'),raw('2026-10-25 01:00',3,'2026-10-25')]}))
    zones=compile_zones(g14()['config'])
    first=datetime(2026,10,25,2,tzinfo=TZ,fold=0)
    second=datetime(2026,10,25,2,tzinfo=TZ,fold=1)
    assert utc_key(first) != utc_key(second)
    assert zone_for(first,zones,set()).kompas_level == 0
    assert zone_for(second,zones,set()).kompas_level == 3


def test_missing_hours_are_not_priced_using_cheapest_zone(database):
    when=datetime(2026,1,9,17,tzinfo=TZ)
    with pytest.raises(TariffValidationError,match='Brak strefy'):
        zone_state(g14(),when)
    static=copy.deepcopy(PRESETS[0])
    result=analyze([g14(),static],[ConsumptionSample(when,1)],when.date(),when.date())
    assert result['tariffs'][0]['tariff_id'] == static['id']
    assert result['tariffs'][1]['error'] is not None


def test_g14_analysis_and_mqtt_use_same_local_data(database):
    rows=[raw('2026-01-09 16:00',0),raw('2026-01-09 17:00',3)]
    db.save_kompas(parse_rows({'value': rows}))
    tariff=g14();tariff['config']['fixed_fees']=[];tariff['config']['capacity_fee']=None
    when=datetime(2026,1,9,17,tzinfo=TZ)
    result=analyze([tariff],[ConsumptionSample(when,10000)],when.date(),when.date())['tariffs'][0]
    assert result['error'] is None
    assert result['zones'][0]['kwh'] == 10000
    assert price_state(tariff,'gross',when)['state'] == pytest.approx(result['total_pln']/10000)
    assert zone_state(tariff,when)['state'] == 'Zalecane użytkowanie (S1)'
    assert price_state(tariff,'net',when)['state'] < price_state(tariff,'net',datetime(2026,1,9,18,tzinfo=TZ))['state']


def test_old_revisions_cannot_overwrite_new_cache(database):
    db.save_kompas(parse_rows({'value':[raw(level=3,pub='2026-01-09 15:00:00')]}))
    db.save_kompas(parse_rows({'value':[raw(level=0)]}))
    assert list(db.kompas_levels().values()) == [3]


def test_import_checkpoint_and_reuse(database):
    async def scenario():
        cache=KompasCache()
        await cache.http.aclose()
        calls=[]
        next_url='https://api.raporty.pse.pl/api/pdgsz?cursor=page2'
        def handler(request):
            calls.append(str(request.url))
            if len(calls)==1:
                return httpx.Response(200,json={'value':[raw(level=0)],'nextLink':next_url})
            if len(calls)==2:
                return httpx.Response(503)
            return httpx.Response(200,json={'value':[raw('2026-01-09 17:00',1)]})
        cache.http=httpx.AsyncClient(transport=httpx.MockTransport(handler))
        with pytest.raises(httpx.HTTPStatusError):
            await cache.pages(cache.query(date(2026,1,9),date(2026,1,9)),archive_target='2026-01-09')
        assert db.get_setting('kompas_history_next') == next_url
        assert db.kompas_summary()['hours']==1
        await cache.pages(db.get_setting('kompas_history_next'),archive_target='2026-01-09')
        assert db.get_setting('kompas_history_through')=='2026-01-09'
        assert db.get_setting('kompas_history_next')==''
        assert db.kompas_summary()['hours']==2
        await cache.close()
    asyncio.run(scenario())


def test_rejects_pagination_to_untrusted_host(database):
    async def scenario():
        cache=KompasCache();await cache.http.aclose()
        cache.http=httpx.AsyncClient(transport=httpx.MockTransport(lambda request: httpx.Response(200,json={'value':[raw()],'nextLink':'https://evil.example/steal'})))
        with pytest.raises(ValueError): await cache.pages(cache.query('2026-01-09','2026-01-09'))
        assert db.kompas_summary()['hours']==0
        await cache.close()
    asyncio.run(scenario())


def test_dynamic_config_requires_four_explicit_levels():
    tariff=g14()
    tariff['config']['zones'][0]['kompas_level']=1
    with pytest.raises(TariffValidationError): compile_zones(tariff['config'])


def test_day_gaps_respect_spring_and_autumn_dst(database):
    for day in [date(2026,3,29),date(2026,10,25)]:
        start=datetime(day.year,day.month,day.day,tzinfo=TZ).astimezone(timezone.utc)
        from datetime import timedelta
        stop=datetime.combine(day+timedelta(days=1),datetime.min.time(),tzinfo=TZ).astimezone(timezone.utc)
        rows=[];cursor=start
        while cursor<stop:
            rows.append(raw(cursor.replace(tzinfo=None).isoformat(' '),0,day.isoformat()))
            cursor+=timedelta(hours=1)
        db.save_kompas(parse_rows({'value':rows}))
    db.set_setting('kompas_history_through','2026-10-25')
    gaps={row['day'] for row in db.kompas_gaps()}
    assert '2026-03-29' not in gaps
    assert '2026-10-25' not in gaps
    assert '2026-03-30' in gaps


def test_api_g14_edit_preserves_dynamic_source_and_levels(database):
    from fastapi.testclient import TestClient
    from tauronizer.main import app
    with TestClient(app) as client:
        preset=client.get('/api/tariffs').json()['tariffs'][-1]
        assert preset['preset_id']=='g14dynamic'
        config=preset['config']
        config['zones'].reverse()
        updated=client.put('/api/tariffs/'+preset['id'],json={'name':preset['name'],'description':preset['description'],'config':config})
        assert updated.status_code==200,updated.text
        config=updated.json()['config']
        assert config['zone_source']=='pse_kompas'
        assert [row['kompas_level'] for row in config['zones']]==[0,1,2,3]
        assert all(not row['is_default'] for row in config['zones'])
        status=client.get('/api/kompas')
        assert status.status_code==200


def test_holiday_does_not_override_kompas_level(database):
    from tauronizer.tariffs import polish_holidays
    db.save_kompas(parse_rows({'value':[raw('2026-01-06 16:00',3,'2026-01-06')]}))
    zones=compile_zones(g14()['config'])
    assert zone_for(datetime(2026,1,6,17,tzinfo=TZ),zones,polish_holidays(2026)).kompas_level==3
