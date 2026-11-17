"""Independent checks against the official source tables and tariff boundaries."""
from datetime import date, datetime, timezone
import copy

import pytest

from tauronizer import db
from tauronizer.calc import ConsumptionSample, analyze
from tauronizer.models import TariffCreate
from tauronizer.main import _validated_config
from tauronizer.tariffs import PRESETS, TZ, compile_zones, holidays_between, preset_by_id, zone_for


@pytest.mark.parametrize('id,prices,fixed',[
    ('pge_g11',[(.4982,.3469)],9.98),
    ('pge_g12',[(.5656,.4014),(.5656,.4014),(.3718,.0765)],14.40),
    ('pge_g12w',[(.5821,.4276),(.5821,.4276),(.4235,.0845)],14.98),
    ('pge_g12n',[(.5511,.3470),(.3912,.0347)],14.40),
    ('enea_g11',[(.4980,.2456)],10.41),
    ('enea_g12',[(.5779,.2779),(.3369,.0913)],14.56),
    ('enea_g12w',[(.6518,.2702),(.3465,.0813)],26.23),
])
def test_official_net_prices(id,prices,fixed):
    config=preset_by_id(id)['config']
    assert [(z['energy_net'],z['distribution_net']) for z in config['zones']]==prices
    assert config['fixed_fees'][0]['net_monthly']==fixed
    assert [f['net_per_kwh'] for f in config['variable_fees']]==[.0332,.0073,.003]
    assert config['excise_net_per_kwh']==.005
    assert config['vat_percent']==23
    assert config['capacity_fee']['net_monthly_rates']==[4.29,10.31,17.18,24.05]
    assert config['reference']['valid_from']=='2026-10-01'
    assert config['reference']['checked_on']=='2026-11-17'
    assert len(config['reference']['sources'])>=2


def rate(id, day, hour):
    config=preset_by_id(id)['config']
    zone=zone_for(datetime.combine(day,datetime.min.time(),tzinfo=TZ).replace(hour=hour),
                  compile_zones(config),holidays_between(day,day))
    return zone.energy_net


@pytest.mark.parametrize('id,high,low', [('pge_g12',.5656,.3718),('pge_g12w',.5821,.4235)])
def test_pge_seasonal_afternoon_boundaries(id,high,low):
    assert [rate(id,date(2026,1,5),h) for h in [12,13,14,15,17,21,22]]==[high,low,low,high,high,high,low]
    assert [rate(id,date(2026,7,6),h) for h in [12,13,14,15,16,17,22]]==[high,high,high,low,low,high,low]


def test_pge_weekends_holidays_and_sunday_tariff():
    saturday,sunday,holiday=date(2026,1,10),date(2026,1,11),date(2026,12,24)
    assert rate('pge_g12',saturday,10)==.5656
    assert rate('pge_g12w',saturday,10)==.4235
    assert rate('pge_g12w',holiday,10)==.4235
    assert rate('pge_g12n',saturday,0)==.5511
    assert rate('pge_g12n',saturday,1)==.3912
    assert rate('pge_g12n',saturday,4)==.3912
    assert rate('pge_g12n',saturday,5)==.5511
    assert rate('pge_g12n',saturday,23)==.5511
    assert all(rate('pge_g12n',sunday,h)==.3912 for h in range(24))
    assert all(rate('pge_g12n',holiday,h)==.3912 for h in range(24))


def test_enea_weekend_has_no_afternoon_window_on_workdays():
    workday=date(2026,1,5)
    assert [rate('enea_g12w',workday,h) for h in [5,6,13,14,15,20,21]]==[.3465,.6518,.6518,.6518,.6518,.6518,.3465]
    assert rate('enea_g12w',date(2026,1,10),12)==.3465
    assert rate('enea_g12w',date(2026,1,6),12)==.3465
    assert rate('enea_g12',date(2026,1,10),10)==.5779
    assert rate('enea_g12',workday,13)==.3369
    assert 'Operator ustala dokładne godziny' in preset_by_id('enea_g12')['config']['reference']['note']


def test_standard_tariff_energy_vat_and_excise_added_once():
    tariff=copy.deepcopy(preset_by_id('enea_g11'))
    tariff['config']['fixed_fees']=[]
    tariff['config']['capacity_fee']=None
    tariff['config']['variable_fees']=[]
    day=date(2026,1,5)
    report=analyze([tariff],[ConsumptionSample(datetime(2026,1,5,12,tzinfo=timezone.utc),100)],day,day)
    result=report['tariffs'][0]
    assert result['breakdown']['energy_pln']==49.80
    assert result['breakdown']['distribution_pln']==24.56
    assert result['breakdown']['excise_pln']==.50
    assert result['total_pln']==92.08
    assert round((.4980+.005)*1.23,4)==.6187 # Official ENEA energy gross table.


def test_sources_survive_validation_edits_and_duplicate(tmp_path,monkeypatch):
    monkeypatch.setenv('DATA_DIR',str(tmp_path))
    db.init_db()
    db.add_presets('pge')
    tariff=db.get_tariff('preset_pge_g12')
    payload=TariffCreate(name='Moja PGE',description=tariff['description'],config=tariff['config'])
    payload.config.zones[0].energy_net=.7
    config=_validated_config(payload)
    assert config['reference']==tariff['config']['reference']
    db.update_tariff(tariff['id'],payload.name,payload.description,config)
    duplicate=db.duplicate_tariff(tariff['id'])
    assert duplicate['config']['zones'][0]['energy_net']==.7
    assert duplicate['config']['reference']==tariff['config']['reference']


def test_upgrade_never_adds_unselected_suppliers_or_overwrites_custom_tariffs(tmp_path,monkeypatch):
    monkeypatch.setenv('DATA_DIR',str(tmp_path))
    db.init_db()
    db.add_presets('tauron')
    custom=copy.deepcopy(db.get_tariff('preset_g11')['config'])
    custom['zones'][0]['energy_net']=.9
    db.update_tariff('preset_g11','Moja taryfa','Opis',custom)
    with db._connect() as connection,connection:
        connection.execute("DELETE FROM tariffs WHERE id LIKE 'preset_pge_%' OR id LIKE 'preset_enea_%'")
        db._set_setting(connection,'presets_version','6')
    db.init_db()
    assert db.get_tariff('preset_g11')['config']==custom
    assert db.get_tariff('preset_g11')['name']=='Moja taryfa'
    assert len(db.list_tariffs())==5
    assert db.get_tariff('preset_pge_g12n') is None


def test_default_zones_and_fees_are_independent():
    presets=copy.deepcopy(PRESETS)
    a=next(p for p in presets if p['id']=='pge_g12')
    b=next(p for p in presets if p['id']=='pge_g12w')
    a['config']['fixed_fees'][0]['net_monthly']=999
    assert b['config']['fixed_fees'][0]['net_monthly']==14.98
    for preset in presets:
        if preset['id'].startswith(('pge_','enea_')):
            zones=compile_zones(preset['config'])
            assert zones[-1].is_default
            assert sum(z.is_default for z in zones)==1
