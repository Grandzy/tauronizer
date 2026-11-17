from datetime import date, datetime, timedelta, timezone
import asyncio
import copy

import httpx
import pytest
from fastapi.testclient import TestClient

from tauronizer import db
from tauronizer.calc import ConsumptionSample, analyze
from tauronizer.export_prices import ExportPriceCache, parse_rce, parse_rcem
from tauronizer.main import app
from tauronizer.models import ProsumerSettings
from tauronizer.prosumer import ProsumerCalculation, paired_energy
from tauronizer.tariffs import TZ


@pytest.fixture(autouse=True)
def database(tmp_path, monkeypatch):
    monkeypatch.setenv('DATA_DIR', str(tmp_path))
    db.init_db()


def tariff(id='simple', energy=1, distribution=.5):
    return dict(id=id,name=id,config=dict(zones=[dict(id='all',name='Cała doba',days=list(range(7)),intervals=['00:00-24:00'],
        energy_net=energy,distribution_net=distribution,is_default=True)],
        fixed_fees=[dict(name='Stała',net_monthly=10)],variable_fees=[dict(name='OZE',net_per_kwh=.1)],
        excise_net_per_kwh=0,vat_percent=23))


def sample(month, kwh, hour=12, day=1):
    return ConsumptionSample(datetime(2026,month,day,hour,tzinfo=TZ).astimezone(timezone.utc),kwh)


def calculate(mode, imports, exports, start=date(2026,1,1), end=date(2026,2,28), balances=None, tariffs=None, ratio=.8):
    settings = ProsumerSettings(mode=mode, export_entity_id='sensor.export', ratio=ratio,opening_balances=balances or [])
    prices=ProsumerCalculation(settings,imports,exports,start,end)
    ts=tariffs or [tariff()]
    return analyze(ts, imports,start,end,current_tariff=ts[0],prosumer_calculation=prices)


def test_rcem_deposit_available_next_month_and_does_not_pay_distribution():
    db.save_export_prices('rcem',[dict(stamp='2026-01',price_mwh=1000,publication='2026-02-11')])
    report=calculate('rcem',[sample(1,10),sample(2,10)],[sample(1,100),sample(2,0)])
    result=report['tariffs'][0]
    jan,feb=result['prosumer']['months']
    assert jan['credit_created']==123
    assert jan['credit_used']==0
    assert feb['credit_used']==12.3
    assert feb['due_pln']==pytest.approx(feb['purchase_gross_pln']-12.3)
    assert result['prosumer']['closing_balance']==110.7
    assert result['total_pln']==pytest.approx(jan['due_pln']+feb['due_pln'])
    assert result['breakdown']['total_pln'] > result['total_pln']
    assert sum(m['current']['total_pln'] for m in report['monthly_costs'])==pytest.approx(result['total_pln'])


@pytest.mark.parametrize('ratio,remaining',[(.8,2),(.7,3)])
def test_metering_ratio_reduces_variable_charges_but_keeps_fixed(ratio,remaining):
    report=calculate('net_metering',[sample(1,10)],[sample(1,10)],end=date(2026,1,31),ratio=ratio)
    result=report['tariffs'][0]
    assert result['zones'][0]['kwh']==remaining
    assert result['breakdown']['energy_pln']==remaining
    assert result['breakdown']['variable_fees_pln']==pytest.approx(remaining*.1)
    assert result['breakdown']['fixed_pln']>0
    assert result['prosumer']['closing_balance']==0


def test_metering_same_zones_before_highest_distribution():
    t=tariff()
    t['config']['zones']=[dict(id='peak',name='Szczyt',days=list(range(7)),intervals=['07:00-13:00'],energy_net=1,distribution_net=.8),
        dict(id='night',name='Noc',days=list(range(7)),intervals=['00:00-24:00'],energy_net=1,distribution_net=.1,is_default=True)]
    # 8 kWh in each zone must cover its own zone first: 2 kWh remain in each.
    report=calculate('net_metering',[sample(1,10,12),sample(1,10,3)],[sample(1,10,12),sample(1,10,3)],
        end=date(2026,1,31),tariffs=[t])
    zones={z['id']:z for z in report['tariffs'][0]['zones']}
    assert zones['peak']['kwh']==2
    assert zones['night']['kwh']==2
    assert report['tariffs'][0]['prosumer']['closing_balance']==0


def test_expiry_and_refund_cap_opening_deposit():
    r=calculate('rcem',[sample(1,0),sample(2,0)],[sample(1,0),sample(2,0)],
        balances=[dict(month='2025-02',amount=100,export_value_pln=100)])['tariffs'][0]['prosumer']
    assert r['months'][0]['balance']==100
    assert r['months'][1]['expired']==100
    assert r['months'][1]['refundable_pln']==20
    assert r['closing_balance']==0


def test_metering_credit_survives_anniversary_month_then_expires():
    r=calculate('net_metering',[sample(1,0),sample(2,0)],[sample(1,0),sample(2,0)],
        balances=[dict(month='2025-01',amount=10)])['tariffs'][0]['prosumer']
    assert r['months'][0]['balance']==10
    assert r['months'][1]['expired']==10


def test_fifo_deposit_consumption():
    r=calculate('rcem',[sample(1,10)],[sample(1,0)],end=date(2026,1,31),
        balances=[dict(month='2025-12',amount=20),dict(month='2025-02',amount=10)])['tariffs'][0]['prosumer']
    lots=r['closing_lots']
    assert len(lots)==1
    assert lots[0]['available']=='2025-12'
    assert lots[0]['amount']==pytest.approx(17.7)


def test_rce_negative_quarters_clamped_and_equal_hour_allocation():
    stamp=sample(1,1).timestamp
    db.save_export_prices('rce',[dict(stamp=(stamp+timedelta(minutes=i*15)).isoformat(),price_mwh=p,publication='2026-01-01')
        for i,p in enumerate([-100,200,400,600])])
    r=calculate('rce',[sample(1,0)],[sample(1,4)],end=date(2026,1,31))['tariffs'][0]['prosumer']
    assert r['months'][0]['export_value_pln']==1.2
    assert r['months'][0]['credit_created']==1.48
    assert r['closing_lots'][0]['amount']==1.48


def test_missing_rce_does_not_become_zero_export_income():
    report=calculate('rce',[sample(1,10)],[sample(1,2)],end=date(2026,1,31))
    assert report['tariffs'][0]['total_pln'] is None
    assert 'Brak kompletu cen RCE' in report['tariffs'][0]['error']


def test_missing_month_cannot_continue_ledger():
    report=calculate('net_metering',[sample(1,10)],[sample(1,0)])
    assert 'Brak wspólnych statystyk' in report['tariffs'][0]['error']


def test_joint_hours_zero_valid_missing_export_excluded_and_vector_balance():
    imports=[sample(1,10),sample(1,5,13),sample(1,3,14)]
    exports=[sample(1,4),sample(1,0,13),sample(1,20,15)]
    i,e=paired_energy(imports,exports)
    assert [s.kwh for s in i]==[6,5]
    assert [s.kwh for s in e]==[0,0]
    assert len(i)==2


def test_dst_repeated_hour_not_merged():
    first=datetime(2026,10,25,0,tzinfo=timezone.utc)
    imports=[ConsumptionSample(first,3),ConsumptionSample(first+timedelta(hours=1),4)]
    exports=[ConsumptionSample(s.timestamp,1) for s in imports]
    i,e=paired_energy(imports,exports)
    assert [s.kwh for s in i]==[2,3]


def test_global_winner_month_chart_uses_settled_costs():
    a,b=tariff('a',energy=1,distribution=.1),tariff('b',energy=.1,distribution=.5)
    report=calculate('rcem',[sample(1,100),sample(2,10)],[sample(1,0),sample(2,0)],
        tariffs=[a,b],balances=[dict(month='2025-12',amount=1000)])
    # A has expensive energy but the deposit covers it; low distribution wins.
    assert report['cheapest_tariff_id']=='a'
    assert {m['recommended']['tariff_id'] for m in report['monthly_costs']}=={'a'}
    assert sum(m['recommended']['total_pln'] for m in report['monthly_costs'])==pytest.approx(report['tariffs'][0]['total_pln'])


def test_rcem_corrected_price_and_missing_rows():
    html='<table><tr><th>2026</th></tr><tr><td>luty</td></tr><tr><td>RCEm</td><td>339,01</td><td>11.03.2026</td></tr><tr><td>skorygowana RCEm*</td><td>331,39</td><td>11.06.2026</td></tr></table>'
    assert parse_rcem(html)==[dict(stamp='2026-02',price_mwh=331.39,publication='2026-06-11')]
    with pytest.raises(ValueError): parse_rcem('<h1>Maintenance</h1>')


def test_rce_timestamp_is_end_of_quarter_and_dst_utc():
    row=dict(dtime_utc='2026-10-25 00:15:00',publication_ts_utc='2026-10-24 12:00:00',business_date='2026-10-25',rce_pln=-10)
    assert parse_rce(dict(value=[row]))[0]['stamp']=='2026-10-25T00:00:00+00:00'
    with pytest.raises(ValueError):parse_rce(dict(value=[{**row,'rce_pln':float('nan')}]))


def test_pse_cached_month_not_downloaded_twice_and_host_validation():
    async def scenario():
        cache=ExportPriceCache()
        await cache.http.aclose()
        calls=[]
        def response(request):
            calls.append(str(request.url))
            start=datetime(2026,1,1,tzinfo=TZ).astimezone(timezone.utc)
            return httpx.Response(200,json=dict(value=[dict(dtime_utc=(start+timedelta(minutes=15*(i+1))).isoformat(),
                publication_ts_utc='2025-12-31 12:00:00',business_date=(start+timedelta(minutes=15*i)).astimezone(TZ).date().isoformat(),rce_pln=100)
                for i in range(31*96)]))
        cache.http=httpx.AsyncClient(transport=httpx.MockTransport(response))
        await cache.month(date(2026,1,1))
        await cache.month(date(2026,1,1))
        assert len(calls)==1
        db.set_setting('rce_month_2026-02','https://evil.example/api/rce-pln')
        with pytest.raises(ValueError):await cache.month(date(2026,2,1))
        assert len(calls)==1
        await cache.close()
    asyncio.run(scenario())


def test_price_revision_does_not_roll_back():
    db.save_export_prices('rcem',[dict(stamp='2026-01',price_mwh=400,publication='2026-03-11')])
    db.save_export_prices('rcem',[dict(stamp='2026-01',price_mwh=500,publication='2026-02-11')])
    assert db.export_prices('rcem','2026-01','2026-02')=={'2026-01':400}


def test_api_settings_and_distinct_entities_and_history():
    class HA:
        async def get_entity(self,id):return {'attributes':{'friendly_name':id}}
        async def get_statistics(self,id,start,end):return [sample(1,10 if id=='sensor.import' else 5)],'kWh'
        async def close(self):pass
    with TestClient(app) as client:
        app.state.ha=HA()
        settings=dict(mode='net_metering',export_entity_id='sensor.export',ratio=.8,opening_balances=[])
        assert client.put('/api/prosumer',json=settings).status_code==200
        assert client.get('/api/prosumer').json()['settings']==settings
        body=dict(entity_id='sensor.import',start='2026-01-01',end='2026-01-31',tariff_ids=['preset_g11'])
        response=client.post('/api/analyze',json=body)
        assert response.status_code==200,response.text
        result=response.json()
        assert result['prosumer']['incomplete'] is True
        assert result['prosumer']['export_quality']['received_hours']==1
        assert result['tariffs'][0]['prosumer']['mode']=='net_metering'
        saved=client.get('/api/analyses/'+result['id']).json()['result']
        assert saved['prosumer']['settings']==settings
        assert saved['tariffs'][0]['prosumer']==result['tariffs'][0]['prosumer']
        assert client.post('/api/analyze',json={**body,'prosumer':{**settings,'export_entity_id':'sensor.import'}}).status_code==400
        ordinary=client.post('/api/analyze',json={**body,'prosumer':{'mode':'off'}}).json()
        assert 'prosumer' not in ordinary


def test_common_pool_offsets_highest_distribution_first():
    t=tariff()
    t['config']['zones']=[dict(id='peak',name='Szczyt',days=list(range(7)),intervals=['07:00-13:00'],energy_net=1,distribution_net=.8),
        dict(id='night',name='Noc',days=list(range(7)),intervals=['00:00-24:00'],energy_net=1,distribution_net=.1,is_default=True)]
    result=calculate('net_metering',[sample(1,10,12),sample(1,10,3)],[sample(1,0,12)],end=date(2026,1,31),tariffs=[t],
        balances=[dict(month='2025-12',amount=5)])['tariffs'][0]
    assert {z['id']:z['kwh'] for z in result['zones']}=={'peak':5,'night':10}


def test_unknown_opening_zone_is_not_silently_reassigned():
    result=calculate('net_metering',[sample(1,10)],[sample(1,0)],end=date(2026,1,31),
        balances=[dict(month='2025-12',amount=5,zone_id='invalid')])['tariffs'][0]
    assert result['total_pln'] is None
    assert 'nie istnieje' in result['error']


def test_rce_refund_limit_is_thirty_percent():
    result=calculate('rce',[sample(1,0)],[sample(1,0)],end=date(2026,1,31),
        balances=[dict(month='2025-01',amount=80,export_value_pln=100)])['tariffs'][0]['prosumer']
    # January 2025 was before the raised cap; an opening lot assigned March has the new cap.
    assert result['refundable_pln']==20
    result=calculate('rce',[sample(3,0)],[sample(3,0)],start=date(2026,3,1),end=date(2026,3,31),
        balances=[dict(month='2025-03',amount=80,export_value_pln=100)])['tariffs'][0]['prosumer']
    assert result['refundable_pln']==30


def test_opening_deposit_can_be_assigned_in_first_analysis_month():
    r=calculate('rcem',[sample(1,10)],[sample(1,0)],end=date(2026,1,31),
        balances=[dict(month='2026-01',amount=20)])['tariffs'][0]['prosumer']
    assert r['months'][0]['credit_used']==12.3
    assert r['closing_balance']==7.7


def test_pse_pagination_resumes_after_failure_without_losing_saved_page():
    async def scenario():
        cache=ExportPriceCache()
        await cache.http.aclose()
        following='https://api.raporty.pse.pl/api/rce-pln?$after=second'
        calls=[]
        failed=False
        def response(request):
            nonlocal failed
            calls.append(str(request.url))
            row=dict(dtime_utc='2026-01-01 00:15:00',publication_ts_utc='2025-12-31 12:00:00',business_date='2026-01-01',rce_pln=100)
            if '$after=second' in str(request.url):
                if not failed:
                    failed=True
                    return httpx.Response(503)
                return httpx.Response(200,json={'value':[{**row,'dtime_utc':'2026-01-01 00:30:00'}]})
            return httpx.Response(200,json={'value':[row],'nextLink':following})
        cache.http=httpx.AsyncClient(transport=httpx.MockTransport(response))
        with pytest.raises(httpx.HTTPStatusError):await cache.month(date(2026,1,1))
        assert db.get_setting('rce_month_2026-01')==following
        assert len(db.export_prices('rce','2026-01','2026-02'))==1
        await cache.month(date(2026,1,1))
        assert len(calls)==3
        assert len(db.export_prices('rce','2026-01','2026-02'))==2
        assert db.get_setting('rce_month_2026-01')!='done' # Incomplete archive is retried.
        await cache.close()
    asyncio.run(scenario())
