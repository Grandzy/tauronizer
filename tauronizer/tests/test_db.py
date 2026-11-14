from __future__ import annotations

import json

from tauronizer import db
from tauronizer.tariffs import PRESETS


def preset_config(preset_id: str) -> dict:
    for preset in PRESETS:
        if preset["id"] == preset_id:
            return preset["config"]
    raise AssertionError(preset_id)


def test_init_seeds_current_g13_definition(tmp_path, monkeypatch) -> None:
    monkeypatch.setenv("DATA_DIR", str(tmp_path))
    db.init_db()

    tariff = db.get_tariff("preset_g13")
    assert tariff is not None
    ids = {zone["id"] for zone in tariff["config"]["zones"]}
    assert ids == {
        "szczyt_przedpoludniowy",
        "szczyt_popoudniowy_zima",
        "szczyt_popoudniowy_lato",
        "pozaszczyt",
    }


def test_legacy_database_without_hashes_is_refreshed(tmp_path, monkeypatch) -> None:
    monkeypatch.setenv("DATA_DIR", str(tmp_path))
    db.init_db()

    with db._connect() as connection, connection:
        connection.execute(
            "UPDATE tariffs SET config = ? WHERE id = 'preset_g13'",
            (json.dumps({"zones": [{"id": "stary"}]}),),
        )
        connection.execute("DELETE FROM settings WHERE key = 'preset_hashes'")
        db._set_setting(connection, "presets_version", "1")

    db.init_db()

    g13 = db.get_tariff("preset_g13")
    assert any(zone.get("months") for zone in g13["config"]["zones"])


def test_preset_upgrade_keeps_user_edits(tmp_path, monkeypatch) -> None:
    monkeypatch.setenv("DATA_DIR", str(tmp_path))
    db.init_db()

    old_g13 = {"zones": [{"id": "stary", "name": "Stara strefa"}]}
    edited_g12 = json.loads(json.dumps(preset_config("g12")))
    edited_g12["zones"][0]["energy_net"] = 9.99

    with db._connect() as connection, connection:
        connection.execute(
            "UPDATE tariffs SET config = ? WHERE id = 'preset_g13'",
            (json.dumps(old_g13),),
        )
        connection.execute(
            "UPDATE tariffs SET config = ? WHERE id = 'preset_g12'",
            (json.dumps(edited_g12),),
        )
        # Hashes of the previously shipped version: g13 untouched, g12 edited.
        hashes = {
            "g11": db._config_hash(preset_config("g11")),
            "g12": db._config_hash(preset_config("g12")),
            "g12w": db._config_hash(preset_config("g12w")),
            "g13": db._config_hash(old_g13),
        }
        db._set_setting(connection, "preset_hashes", json.dumps(hashes))
        db._set_setting(connection, "presets_version", "1")

    db.init_db()

    g13 = db.get_tariff("preset_g13")
    assert any(zone.get("months") for zone in g13["config"]["zones"])
    g12 = db.get_tariff("preset_g12")
    assert g12["config"]["zones"][0]["energy_net"] == 9.99


def test_second_upgrade_keeps_customised_preset(tmp_path, monkeypatch):
    monkeypatch.setenv('DATA_DIR', str(tmp_path))
    db.init_db()
    custom = json.loads(json.dumps(preset_config('g12')))
    custom['zones'][0]['energy_net'] = 9.99
    db.update_tariff('preset_g12', 'Moja G12', 'Opis', custom)
    for _ in range(2):
        with db._connect() as connection, connection:
            db._set_setting(connection, 'presets_version', '2')
        db.init_db()
        assert db.get_tariff('preset_g12')['config'] == custom


def test_version_two_presets_receive_2026_rates(tmp_path, monkeypatch):
    monkeypatch.setenv('DATA_DIR', str(tmp_path))
    db.init_db()
    old = json.loads(json.dumps(preset_config('g11')))
    old.pop('capacity_fee')
    old['zones'][0]['energy_net'] = 0.46
    old['variable_fees'] = [{'name': 'Opłata mocowa', 'net_per_kwh': 0.0249}]
    with db._connect() as connection, connection:
        connection.execute("UPDATE tariffs SET config = ? WHERE id = 'preset_g11'", (json.dumps(old),))
        hashes = db._preset_hashes(connection)
        hashes['g11'] = db._config_hash(old)
        db._set_setting(connection, 'preset_hashes', json.dumps(hashes))
        db._set_setting(connection, 'presets_version', '2')
    db.init_db()
    assert db.get_tariff('preset_g11')['config'] == preset_config('g11')
