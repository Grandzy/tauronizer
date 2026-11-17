from __future__ import annotations

import copy
import json

import pytest

from tauronizer import db
from tauronizer.tariffs import preset_by_id


@pytest.fixture
def database(tmp_path, monkeypatch):
    monkeypatch.setenv('DATA_DIR', str(tmp_path))
    db.init_db()


def test_new_installation_and_restart_have_no_tariffs(database):
    assert db.list_tariffs() == []
    db.init_db()
    assert db.list_tariffs() == []
    assert [(o['id'],o['total'],o['missing']) for o in db.preset_catalog()] == [
        ('tauron',5,5),('pge',4,4),('enea',3,3)]


@pytest.mark.parametrize('operator,count,prefix', [('tauron',5,'Tauron '),('pge',4,'PGE '),('enea',3,'ENEA ')])
def test_adds_only_requested_operator(database,operator,count,prefix):
    assert db.add_presets(operator)==dict(added=count,skipped=0)
    assert len(db.list_tariffs())==count
    assert all(t['name'].startswith(prefix) for t in db.list_tariffs())
    db.init_db()
    assert len(db.list_tariffs())==count
    assert next(o for o in db.preset_catalog() if o['id']==operator)['missing']==0


def test_repeated_import_preserves_every_existing_field(database):
    db.add_presets('tauron')
    tariff=db.get_tariff('preset_g12')
    config=copy.deepcopy(tariff['config'])
    config['zones'][0]['energy_net']=.99
    db.update_tariff(tariff['id'],'Moja nazwa','Mój opis',config)
    before=db.list_tariffs()
    assert db.add_presets('tauron')==dict(added=0,skipped=5)
    assert db.list_tariffs()==before


def test_deleted_preset_does_not_return_on_update(database,monkeypatch):
    db.add_presets('tauron')
    db.delete_tariff('preset_g12')
    monkeypatch.setattr(db,'PRESET_VERSION',999)
    db.init_db()
    assert db.get_tariff('preset_g12') is None
    assert db.get_tariff('preset_pge_g11') is None
    assert db.add_presets('tauron')==dict(added=1,skipped=4)
    assert db.get_tariff('preset_g12') is not None


def test_update_preserves_custom_tariff_duplicate_and_all_settings(database,monkeypatch):
    config=copy.deepcopy(preset_by_id('g12')['config'])
    config['zones'][0]['energy_net']=.8123
    custom=db.create_tariff('Własna taryfa','Ręcznie wpisane stawki',config)
    duplicate=db.duplicate_tariff(custom['id'])
    db.set_setting('sensor_tariff_id',custom['id'])
    db.set_setting('prosumer_settings',json.dumps({'mode':'off'}))
    before=db.list_tariffs()
    for version in (8,9,10):
        monkeypatch.setattr(db,'PRESET_VERSION',version)
        db.init_db()
        assert db.list_tariffs()==before  # Includes IDs, timestamps, name, description and full config.
        assert db.get_tariff(duplicate['id'])['preset_id'] is None
        assert db.get_setting('sensor_tariff_id')==custom['id']
        assert db.get_setting('prosumer_settings')==json.dumps({'mode':'off'})
    db.add_presets('pge')
    assert db.get_tariff(custom['id'])==custom
    assert db.get_tariff(duplicate['id'])==duplicate


@pytest.mark.parametrize('change', ['name','description','config'])
def test_legacy_database_without_hashes_never_overwrites_edits(database,change):
    db.add_presets('tauron')
    original=db.get_tariff('preset_g13')
    values={k:copy.deepcopy(original[k]) for k in ('name','description','config')}
    if change=='config':
        values['config']['zones'][0]['energy_net']=.9123
    else:
        values[change]='Własna wartość'
    db.update_tariff(original['id'],**values)
    before=db.list_tariffs()
    with db._connect() as connection, connection:
        connection.execute("DELETE FROM settings WHERE key IN ('preset_hashes','presets_seeded')")
        db._set_setting(connection,'presets_version','1')
    db.init_db()
    assert db.list_tariffs()==before


def test_legacy_untouched_presets_also_stay_intact(database,monkeypatch):
    db.add_presets('pge')
    before=db.list_tariffs()
    with db._connect() as connection,connection:
        db._set_setting(connection,'presets_seeded','1')
        db._set_setting(connection,'presets_version','7')
        db._set_setting(connection,'preset_hashes','invalid legacy data')
    monkeypatch.setattr(db,'PRESET_VERSION',999)
    db.init_db()
    assert db.list_tariffs()==before
    assert len(db.list_tariffs())==4


def test_unknown_operator_does_not_change_data(database):
    with pytest.raises(ValueError):db.add_presets('unknown')
    assert db.list_tariffs()==[]
