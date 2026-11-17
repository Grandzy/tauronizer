"""Purchase feeds, calendar alignment, shared pricing and durable history."""
import asyncio
import copy
from datetime import date, datetime, timedelta, timezone

import httpx
import pytest

from tauronizer import db
from tauronizer.calc import ConsumptionSample, analyze
from tauronizer.models import ProsumerSettings, TariffCreate
from tauronizer.prosumer import ProsumerCalculation
from tauronizer.purchase_prices import PurchasePriceCache, day_hours, energy_price, parse_day, source_for
from tauronizer.sensors import (SensorPublisher, price_state, PRICE_AVAILABILITY_TOPIC,
                                PRICE_STATE_TOPIC, AVAILABILITY_TOPIC, STATE_TOPIC)
from tauronizer.tariffs import TZ, TariffValidationError, compile_zones, holidays_between, preset_by_id, zone_for


@pytest.fixture(autouse=True)
def database(tmp_path, monkeypatch):
    monkeypatch.setenv('DATA_DIR', str(tmp_path))
    db.init_db()


def enea_rows(price='0,7380'):
    return [dict(hour=str(i+1), price=price, info='') for i in range(24)]


def pge_rows(day, price='100', contract='Fix_1'):
    return [dict(attributes=[dict(name='quotationDate', value=f'{day}T{i:02}:00:00+00:00'),
        dict(name='tradingDate', value=f'{day-timedelta(days=1)}T{i:02}:00:00+00:00'),
        dict(name='contract', value=contract),dict(name='price',value=price)]) for i in range(24)]


def tariff(id='enea_g11_dynamic'):
    t = copy.deepcopy(preset_by_id(id))
    t['config'].update(fixed_fees=[],variable_fees=[],capacity_fee=None)
    for z in t['config']['zones']: z['distribution_net'] = .2
    return t


def sample(day, hour=12, kwh=10):
    return ConsumptionSample(datetime.combine(day,datetime.min.time(),TZ).replace(hour=hour).astimezone(timezone.utc),kwh)


def save(source, day, rows=None):
    db.save_purchase_prices(source,parse_day(source,day, rows if rows is not None else (enea_rows() if source=='enea_dynamic' else pge_rows(day))))


def test_enea_gross_to_net_and_excise_vat_added_once():
    day=date(2026,11,17)
    save('enea_dynamic',day)
    t=tariff()
    report=analyze([t],[sample(day)],day,day,current_tariff=t)
    cost=report['tariffs'][0]
    assert cost['error'] is None
    assert cost['breakdown']['energy_pln']==5.95  # .738 / 1.23 - .005 = .595
    assert cost['breakdown']['excise_pln']==.05
    assert cost['total_pln']==9.84  # (6 energy incl excise + 2 distribution) * 1.23
    assert price_state(t,'gross',sample(day).timestamp)['state']==.984
    assert price_state(t,'net',sample(day).timestamp)['state']==.8
    assert report['monthly_costs'][0]['current']['total_pln']==9.84
    assert cost['zones'][0]['price_energy_net']==pytest.approx(.595)


@pytest.mark.parametrize('raw,expected',[('-100',.0855),('1000',1.0855),('9000',4.0855)])
def test_pge_contract_floor_cap_markup(raw,expected):
    day=date(2026,11,17)
    save('pge_fix1',day,pge_rows(day,raw))
    t=tariff('pge_g11_dynamic')
    z=compile_zones(t['config'])[0]
    assert energy_price(t['config'],z,sample(day).timestamp)==pytest.approx(expected)
    p=tariff('pge_g11_dynamic_prosumer')
    assert price_state(p,'net',sample(day).timestamp)['state']==pytest.approx(expected+.0295+.2+.005)


def test_pge_delivery_not_trading_date_and_local_clock():
    day=date(2026,11,17)
    rows=parse_day('pge_fix1',day,pge_rows(day,'738.93'))
    assert rows[0]['stamp']=='2026-11-16T23:00:00+00:00'
    assert rows[0]['value']==pytest.approx(.73893)
    assert round((rows[0]['value']+.082+.005)*1.23,4)==1.0159
    with pytest.raises(ValueError,match='data dostawy'):
        parse_day('pge_fix1',day+timedelta(days=1),pge_rows(day))
    assert source_for({'energy_source':'pge_dynamic'},date(2026,12,31))=='pge_fix1'
    assert source_for({'energy_source':'pge_dynamic'},date(2027,1,1))=='pge_fix2'
    with pytest.raises(ValueError,match='fixing'):
        parse_day('pge_fix2',day,pge_rows(day))


@pytest.mark.parametrize('day',[date(2026,3,29),date(2026,10,25)])
@pytest.mark.parametrize('source',['enea_dynamic','pge_fix1'])
def test_dst_ambiguity_is_not_silently_assigned(day,source):
    assert len(day_hours(day)) in (23,25)
    with pytest.raises(ValueError,match='zmiany czasu'):
        parse_day(source,day,enea_rows() if source=='enea_dynamic' else pge_rows(day))


@pytest.mark.parametrize('change',['missing','duplicate','nan'])
def test_enea_malformed_day_is_atomic(change):
    rows=enea_rows()
    if change=='missing':rows.pop()
    if change=='duplicate':rows[-1]['hour']='1'
    if change=='nan':rows[0]['price']='NaN'
    with pytest.raises(ValueError):parse_day('enea_dynamic',date(2026,11,17),rows)
    assert db.purchase_price_summary()==[]


def test_missing_price_excludes_dynamic_only():
    day=date(2026,11,17)
    t=tariff()
    fixed=copy.deepcopy(preset_by_id('enea_g11'))
    report=analyze([t,fixed],[sample(day)],day,day,current_tariff=t)
    assert report['cheapest_tariff_id']==fixed['id']
    invalid=next(r for r in report['tariffs'] if r['tariff_id']==t['id'])
    assert 'Brak ceny zakupu' in invalid['error']
    assert invalid['total_pln'] is None
    with pytest.raises(TariffValidationError):price_state(t,now=sample(day).timestamp)


def test_negative_enea_price_not_clamped():
    day=date(2026,11,17)
    save('enea_dynamic',day,enea_rows('-0,1230'))
    assert price_state(tariff(),'gross',sample(day).timestamp)['state']==.123  # energy -.1 incl excise + distribution .2


def test_history_cached_across_instances_and_restart_and_no_tariff_changes():
    day=date(2026,11,17)
    t=tariff()
    db.add_presets('enea')
    before=db.list_tariffs()
    requests=[]
    async def go():
        cache=PurchasePriceCache()
        await cache.http.aclose()
        def respond(request):
            requests.append(str(request.url))
            return httpx.Response(200,json=enea_rows())
        cache.http=httpx.AsyncClient(transport=httpx.MockTransport(respond))
        try:
            await cache.ensure([t,t],day,day)
            assert cache.status=='ready'
        finally:await cache.close()
    asyncio.run(go())
    db.init_db()
    asyncio.run(go())
    assert len(requests)==1
    assert requests[0].endswith('/individual/17.11.2026')
    assert db.list_tariffs()==before
    assert db.purchase_price_summary()[0]['hours']==24
    assert db.export_price_summary()==[]


def test_failed_refresh_keeps_cached_prices():
    day=date(2026,11,17)
    save('enea_dynamic',day)
    before=db.purchase_prices('enea_dynamic',day_hours(day)[0].isoformat(),day_hours(day+timedelta(days=1))[0].isoformat())
    async def go():
        cache=PurchasePriceCache()
        await cache.http.aclose()
        cache.http=httpx.AsyncClient(transport=httpx.MockTransport(lambda req:httpx.Response(200,json=enea_rows()[:-1])))
        try:
            with pytest.raises(ValueError):await cache.day('enea_dynamic',day,refresh=True)
        finally:await cache.close()
    asyncio.run(go())
    assert db.purchase_prices('enea_dynamic',min(before),(max(day_hours(day))+timedelta(hours=1)).isoformat())==before


def test_pge_fetches_previous_trading_day_and_next_year_fixing():
    day=date(2027,1,4)
    async def go():
        cache=PurchasePriceCache()
        await cache.http.aclose()
        def respond(request):
            assert request.url.params['date_from']=='2027-01-03 00:00:00'
            assert request.url.params['contract']=='Fix_2'
            return httpx.Response(200,json=pge_rows(day,contract='Fix_2'))
        cache.http=httpx.AsyncClient(transport=httpx.MockTransport(respond))
        try:await cache.ensure([tariff('pge_g11_dynamic')],day,day)
        finally:await cache.close()
    asyncio.run(go())
    assert db.purchase_price_summary()[0]['source']=='pge_fix2'


def test_net_billing_uses_same_purchase_price_and_deposit():
    jan,feb=date(2026,1,5),date(2026,2,5)
    for day in (jan,feb):save('enea_dynamic',day)
    db.save_export_prices('rcem',[dict(stamp='2026-01',price_mwh=1000,publication='2026-02-11'),dict(stamp='2026-02',price_mwh=1000,publication='2026-03-11')])
    imports=[sample(jan),sample(feb)]
    settings=ProsumerSettings(mode='rcem',export_entity_id='sensor.export')
    p=ProsumerCalculation(settings,imports,[sample(jan,kwh=100),sample(feb,kwh=0)],jan,feb)
    t=tariff()
    report=analyze([t],imports,jan,feb,current_tariff=t,prosumer_calculation=p)
    cost=report['tariffs'][0]
    assert cost['error'] is None
    assert cost['total_pln']==12.30  # Jan 9.84; Feb distribution 2.46 (energy paid by deposit)
    assert cost['prosumer']['credit_used_pln']==7.38


def test_missing_energy_keeps_zone_published_but_price_unavailable():
    db.add_presets('enea')
    db.set_setting('sensor_tariff_id','preset_enea_g11_dynamic')
    class MQTT:
        def __init__(self):self.messages=[]
        async def publish_mqtt(self,topic,payload,*,retain):self.messages.append((topic,payload))
    ha=MQTT()
    publisher=SensorPublisher(ha)
    asyncio.run(publisher.refresh())
    assert (AVAILABILITY_TOPIC,'online') in ha.messages
    assert (PRICE_AVAILABILITY_TOPIC,'offline') in ha.messages
    assert any(t==STATE_TOPIC for t,_ in ha.messages)
    assert not any(t==PRICE_STATE_TOPIC for t,_ in ha.messages)
    assert publisher.status=='waiting_data'


def test_all_new_presets_validate_and_compile():
    for id in ('enea_g11_dynamic','enea_g12sezon_dynamic','enea_g13active_dynamic','pge_g11_dynamic','pge_g11_dynamic_prosumer','pge_g12e_dynamic_prosumer'):
        preset=preset_by_id(id)
        TariffCreate(name=preset['name'],description=preset['description'],config=preset['config'])
        compile_zones(preset['config'])


def test_enea_calendar_month_boundaries_and_weekends():
    def rate(id,month,hour,day=15):
        config=preset_by_id(id)['config']
        dt=datetime(2026,month,day,hour,tzinfo=TZ)
        return zone_for(dt,compile_zones(config),holidays_between(dt.date(),dt.date())).distribution_net
    assert [rate('enea_g12sezon_dynamic',1,h) for h in (5,6,10,11,12,13,21,22)]==[.0913,.2779,.2779,.0913,.0913,.2779,.2779,.0913]
    assert [rate('enea_g12sezon_dynamic',7,h) for h in (3,4,5,6,8,9,16,17)]==[.2779,.0913,.0913,.2779,.2779,.0913,.0913,.2779]
    assert [rate('enea_g13active_dynamic',12,h) for h in (6,7,9,10,12,13,19,20,22,23)]==[.2456,.3032,.3032,.2456,.2456,.3032,.3032,.2456,.2456,.073]
    # Saturday/holiday remains governed by monthly table.
    assert rate('enea_g13active_dynamic',8,19)==.3032


def test_api_analysis_uses_cache_and_status_refresh_preserves_tariffs():
    from fastapi.testclient import TestClient
    from tauronizer.main import app
    day=date(2026,11,17)
    save('enea_dynamic',day)
    class HA:
        is_supervisor=False
        async def get_entity(self,id):return dict(attributes=dict(friendly_name='Dom'))
        async def get_statistics(self,*args):return [sample(day)],'kWh'
        async def close(self):pass
    with TestClient(app) as client:
        db.add_presets('enea')
        client.app.state.ha=HA()
        before=db.list_tariffs()
        status=client.get('/api/purchase-prices').json()
        assert status['series'][0]['hours']==24
        assert status['last_update'] is not None
        response=client.post('/api/analyze',json=dict(entity_id='sensor.import',start=str(day),end=str(day),tariff_ids=['preset_enea_g11_dynamic']))
        assert response.status_code==200,response.text
        result=response.json()['tariffs'][0]
        assert result['error'] is None
        assert result['breakdown']['energy_pln']==5.95
        assert client.post('/api/purchase-prices/refresh').status_code==200
        assert db.list_tariffs()==before
