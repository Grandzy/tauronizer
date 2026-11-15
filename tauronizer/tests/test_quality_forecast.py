from datetime import date, datetime, timedelta, timezone
import asyncio
import json

import pytest

from tauronizer import db
from tauronizer.calc import ConsumptionSample
from tauronizer.quality import consumption_coverage
from tauronizer.forecast import dynamic_schedule
from tauronizer.tariffs import TZ


def hourly_samples(day):
    start = datetime.combine(day, datetime.min.time(), TZ).astimezone(timezone.utc)
    stop = datetime.combine(day + timedelta(days=1), datetime.min.time(), TZ).astimezone(timezone.utc)
    return [ConsumptionSample(start + timedelta(hours=i), 0) for i in range(int((stop-start).total_seconds()/3600))]


@pytest.mark.parametrize('day,expected', [(date(2026,3,29),23), (date(2026,10,25),25)])
def test_coverage_uses_real_dst_hours_and_zero_counts_as_observed(day, expected):
    samples = hourly_samples(day)
    report = consumption_coverage(samples, day, day, datetime(2027,1,1,tzinfo=timezone.utc))
    assert report['expected_hours'] == expected
    assert report['received_hours'] == expected
    assert report['percent'] == 100
    assert report['complete'] is True
    assert report['gaps'] == []


def test_coverage_detects_internal_gaps_and_does_not_count_duplicates_or_negative_as_data():
    day = date(2026,1,9)
    samples = hourly_samples(day)
    invalid = ConsumptionSample(samples[7].timestamp, -1)
    samples = samples[:5] + [invalid] + samples[8:] + [samples[0]]
    report = consumption_coverage(samples,day,day,datetime(2027,1,1,tzinfo=timezone.utc))
    assert report['expected_hours'] == 24
    assert report['received_hours'] == 21
    assert report['missing_hours'] == 3
    assert report['percent'] == 87.5
    assert report['duplicate_samples'] == 1
    assert report['invalid_samples'] == 1
    assert report['gaps'][0]['hours'] == 3
    assert report['gap_count'] == 1


def test_coverage_excludes_current_hour_and_future_today_and_preserves_partial_month():
    day = date(2026,1,9)
    now = datetime(2026,1,9,11,30,tzinfo=TZ)  # UTC 10:30, eleven completed local hours
    report = consumption_coverage(hourly_samples(day)[:11],day,day,now)
    assert report['expected_hours'] == 11
    assert report['pending_hours'] == 13
    assert report['missing_hours'] == 0
    assert report['percent'] == 100
    assert report['months'][0]['partial_month'] is True


def test_coverage_tracks_year_boundaries_and_missing_months():
    report = consumption_coverage(hourly_samples(date(2025,12,31)),date(2025,12,31),date(2026,2,1),datetime(2027,1,1,tzinfo=timezone.utc))
    assert [row['month'] for row in report['months']] == ['2025-12','2026-01','2026-02']
    assert report['months'][1]['received_hours'] == 0
    assert report['months'][1]['missing_hours'] == 31 * 24
    assert report['months'][1]['partial_month'] is False


def test_coverage_caps_gap_details_but_keeps_all_counts():
    start = date(2026,1,1)
    samples = [ConsumptionSample(datetime(2026,1,1,tzinfo=TZ).astimezone(timezone.utc) + timedelta(hours=i),1) for i in range(0,31*24,2)]
    report = consumption_coverage(samples,start,date(2026,1,31),datetime(2027,1,1,tzinfo=timezone.utc))
    assert report['gap_count'] == report['missing_hours'] == 372
    assert len(report['gaps']) == 200
    assert report['gaps_truncated'] is True


@pytest.fixture
def database(tmp_path,monkeypatch):
    monkeypatch.setenv('DATA_DIR',str(tmp_path))
    db.init_db()
    return db.get_tariff('preset_g14dynamic')


def seed_plan(today, level_for):
    rows=[]
    start = datetime.combine(today,datetime.min.time(),TZ).astimezone(timezone.utc)
    end = datetime.combine(today+timedelta(days=2),datetime.min.time(),TZ).astimezone(timezone.utc)
    cursor=start
    while cursor<end:
        level=level_for(cursor)
        if level is not None:
            rows.append({'utc_hour':cursor.isoformat(),'business_date':cursor.astimezone(TZ).date().isoformat(),
                         'level':level,'publication_utc':start.isoformat()})
        cursor+=timedelta(hours=1)
    db.save_kompas(rows)


def test_schedule_merges_same_zone_hours_and_finds_change_across_midnight(database):
    now = datetime(2026,1,9,23,30,tzinfo=TZ)
    boundary = datetime(2026,1,10,tzinfo=TZ).astimezone(timezone.utc)
    seed_plan(now.date(),lambda hour: 0 if hour<boundary else 3)
    result=dynamic_schedule(database,now)
    assert len(result['days'])==2
    assert all(day['complete'] for day in result['days'])
    assert len(result['days'][0]['segments'])==1
    assert result['next_change']['at']==boundary.isoformat()
    assert result['next_change']['level']==3
    assert result['next_change']['zone_name'].endswith('(S4)')
    # Variable gross price includes energy, distribution, extras and excise, excluding monthly charges.
    config=database['config'];zone=next(z for z in config['zones'] if z['kompas_level']==3)
    extras=sum(f['net_per_kwh'] for f in config['variable_fees'])+config['excise_net_per_kwh']
    assert result['next_change']['price_gross']==pytest.approx(round((zone['energy_net']+zone['distribution_net']+extras)*1.23,6))


def test_schedule_never_skips_missing_hour_to_claim_next_change(database):
    now=datetime(2026,1,9,17,30,tzinfo=TZ)
    missing=datetime(2026,1,9,18,tzinfo=TZ).astimezone(timezone.utc)
    seed_plan(now.date(),lambda h: 0 if h<missing else None if h==missing else 3)
    result=dynamic_schedule(database,now)
    assert result['next_change'] is None
    assert 'ciągłych' in result['reason']
    assert result['days'][0]['available_hours']==23
    assert any(row['zone_name'] is None for row in result['days'][0]['segments'])


@pytest.mark.parametrize('day,expected',[(date(2026,3,29),23),(date(2026,10,25),25)])
def test_forecast_day_lengths_follow_dst(database,day,expected):
    seed_plan(day,lambda h: 0)
    result=dynamic_schedule(database,datetime.combine(day,datetime.min.time(),TZ))
    assert result['days'][0]['expected_hours']==expected
    assert result['days'][0]['available_hours']==expected
    assert result['next_change'] is None


def test_forecast_distinguishes_both_autumn_two_oclock_hours(database):
    first=datetime(2026,10,25,2,30,tzinfo=TZ,fold=0)
    second=datetime(2026,10,25,2,tzinfo=TZ,fold=1).astimezone(timezone.utc)
    seed_plan(first.date(),lambda h: 0 if h<second else 1)
    result=dynamic_schedule(database,first)
    assert result['next_change']['at']==second.isoformat()
    assert result['next_change']['level']==1


def test_missing_today_and_unpublished_tomorrow_are_explicit(database):
    result=dynamic_schedule(database,datetime(2026,1,9,17,tzinfo=TZ))
    assert result['next_change'] is None
    assert all(day['available_hours']==0 for day in result['days'])
    assert all(day['segments'][0]['zone_name'] is None for day in result['days'])
    assert dynamic_schedule(db.get_tariff('preset_g11'))['days']==[]


def test_next_change_mqtt_uses_selected_tariff_and_becomes_unavailable_without_data(database,monkeypatch):
    import tauronizer.sensors as sensors
    now=datetime(2026,1,9,17,30,tzinfo=TZ)
    boundary=datetime(2026,1,9,18,tzinfo=TZ).astimezone(timezone.utc)
    seed_plan(now.date(),lambda h: 0 if h<boundary else 2)
    original=dynamic_schedule
    monkeypatch.setattr(sensors,'dynamic_schedule',lambda t: original(t,now))
    class Fake:
        def __init__(self): self.messages=[]
        async def publish_mqtt(self,topic,payload,*,retain): self.messages.append((topic,payload,retain))
    async def scenario():
        fake=Fake();publisher=sensors.SensorPublisher(fake)
        db.set_setting('sensor_tariff_id',database['id'])
        await publisher.refresh_next_change()
        messages={t:p for t,p,_ in fake.messages}
        discovery=json.loads(messages[sensors.NEXT_CHANGE_DISCOVERY_TOPIC])
        assert discovery['device_class']=='timestamp'
        assert discovery['availability_topic']!=sensors.AVAILABILITY_TOPIC
        assert discovery['expire_after']==90
        state=json.loads(messages[sensors.NEXT_CHANGE_STATE_TOPIC])
        assert state['state']==boundary.isoformat()
        assert state['attributes']['next_level']==2
        assert state['attributes']['next_zone'].endswith('(S3)')
        assert all(not r for t,_,r in fake.messages if t==sensors.NEXT_CHANGE_STATE_TOPIC)
        db.set_setting('sensor_tariff_id','preset_g11')
        await publisher.refresh_next_change()
        assert fake.messages[-1]==(sensors.NEXT_CHANGE_AVAILABILITY_TOPIC,'offline',False)
        db.set_setting('sensor_tariff_id',database['id'])
        db.save_kompas([{'utc_hour':boundary.isoformat(),'business_date':'2026-01-09','level':0,'publication_utc':'2099-01-01T00:00:00+00:00'}])
        await publisher.refresh_next_change()
        state=json.loads({t:p for t,p,_ in fake.messages}[sensors.NEXT_CHANGE_STATE_TOPIC])
        assert state['state']==(boundary+timedelta(hours=1)).isoformat()
    asyncio.run(scenario())
