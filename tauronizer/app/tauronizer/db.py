"""SQLite persistence for tariffs, settings and saved analyses."""

from __future__ import annotations

import json
import os
import sqlite3
import uuid
from contextlib import contextmanager
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Iterator

from .tariffs import PRESET_OPERATORS, PRESET_VERSION, presets_for_operator

SCHEMA = """
CREATE TABLE IF NOT EXISTS tariffs (
    id TEXT PRIMARY KEY,
    name TEXT NOT NULL,
    description TEXT NOT NULL DEFAULT '',
    preset_id TEXT,
    is_preset INTEGER NOT NULL DEFAULT 0,
    config TEXT NOT NULL,
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS analyses (
    id TEXT PRIMARY KEY,
    created_at TEXT NOT NULL,
    entity_id TEXT NOT NULL,
    entity_name TEXT NOT NULL,
    start TEXT NOT NULL,
    end TEXT NOT NULL,
    days INTEGER NOT NULL,
    total_kwh REAL NOT NULL,
    cheapest_name TEXT,
    cheapest_total_pln REAL,
    max_savings_pln REAL,
    result TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS settings (
    key TEXT PRIMARY KEY,
    value TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS export_prices (
    kind TEXT NOT NULL CHECK(kind IN ('rce','rcem')),
    stamp TEXT NOT NULL,
    price_mwh REAL NOT NULL,
    publication TEXT NOT NULL,
    PRIMARY KEY(kind, stamp)
);
CREATE TABLE IF NOT EXISTS kompas_hours (
    utc_hour TEXT PRIMARY KEY,
    business_date TEXT NOT NULL,
    level INTEGER NOT NULL CHECK(level BETWEEN 0 AND 3),
    publication_utc TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_kompas_date ON kompas_hours(business_date);
CREATE INDEX IF NOT EXISTS idx_analyses_created ON analyses(created_at DESC);
"""

MAX_ANALYSES = 200


def data_dir() -> Path:
    override = os.getenv("DATA_DIR")
    if override:
        path = Path(override)
    elif Path("/data").is_dir():
        path = Path("/data")
    else:
        path = Path.cwd() / "data"
    path.mkdir(parents=True, exist_ok=True)
    return path


def db_path() -> Path:
    return data_dir() / "tauronizer.db"


def utcnow() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat()


@contextmanager
def _connect() -> Iterator[sqlite3.Connection]:
    connection = sqlite3.connect(db_path(), timeout=20)
    connection.row_factory = sqlite3.Row
    try:
        connection.execute("PRAGMA journal_mode=WAL")
        yield connection
    finally:
        connection.close()


def init_db() -> None:
    """Create/migrate storage without installing or mutating any saved tariff.

    This also applies to legacy databases with missing hashes or seed markers.
    Catalog updates never restore deleted presets or overwrite user changes.
    """
    with _connect() as connection:
        connection.executescript(SCHEMA)
        with connection:
            _set_setting(connection, 'presets_version', str(PRESET_VERSION))
            _set_setting(connection, 'schema_version', '3')


def preset_catalog() -> list[dict[str, Any]]:
    with _connect() as connection:
        ids = {row['id'] for row in connection.execute('SELECT id FROM tariffs')}
    result = []
    for operator, name in PRESET_OPERATORS.items():
        presets = presets_for_operator(operator)
        installed = sum(f"preset_{preset['id']}" in ids for preset in presets)
        result.append(dict(id=operator, name=name, total=len(presets), installed=installed,
                           missing=len(presets)-installed))
    return result


def add_presets(operator: str) -> dict[str, int]:
    """Explicit opt-in: insert only missing IDs, including when called repeatedly."""
    presets = presets_for_operator(operator)
    with _connect() as connection, connection:
        added = sum(_insert_preset(connection, preset) for preset in presets)
    return {'added': added, 'skipped': len(presets)-added}


def _get_setting(connection: sqlite3.Connection, key: str) -> str | None:
    row = connection.execute("SELECT value FROM settings WHERE key = ?", (key,)).fetchone()
    return row["value"] if row else None


def _set_setting(connection: sqlite3.Connection, key: str, value: str) -> None:
    connection.execute(
        "INSERT INTO settings(key, value) VALUES(?, ?) "
        "ON CONFLICT(key) DO UPDATE SET value = excluded.value",
        (key, value),
    )


def _insert_preset(connection: sqlite3.Connection, preset: dict[str, Any]) -> bool:
    now = utcnow()
    cursor = connection.execute(
        "INSERT OR IGNORE INTO tariffs"
        "(id, name, description, preset_id, is_preset, config, created_at, updated_at) "
        "VALUES(?, ?, ?, ?, 1, ?, ?, ?)",
        (
            f"preset_{preset['id']}",
            preset["name"],
            preset["description"],
            preset["id"],
            json.dumps(preset["config"], ensure_ascii=False),
            now,
            now,
        ),
    )

    return cursor.rowcount > 0


def _row_to_tariff(row: sqlite3.Row) -> dict[str, Any]:
    try:
        config = json.loads(row["config"])
    except (TypeError, ValueError):
        config = {}
    return {
        "id": row["id"],
        "name": row["name"],
        "description": row["description"],
        "preset_id": row["preset_id"],
        "is_preset": bool(row["is_preset"]),
        "config": config,
        "created_at": row["created_at"],
        "updated_at": row["updated_at"],
    }


def list_tariffs() -> list[dict[str, Any]]:
    with _connect() as connection:
        rows = connection.execute(
            "SELECT * FROM tariffs ORDER BY is_preset DESC, name COLLATE NOCASE ASC"
        ).fetchall()
    return [_row_to_tariff(row) for row in rows]


def get_tariff(tariff_id: str) -> dict[str, Any] | None:
    with _connect() as connection:
        row = connection.execute("SELECT * FROM tariffs WHERE id = ?", (tariff_id,)).fetchone()
    return _row_to_tariff(row) if row else None


def create_tariff(
    name: str,
    description: str,
    config: dict[str, Any],
    *,
    preset_id: str | None = None,
    is_preset: bool = False,
) -> dict[str, Any]:
    tariff_id = uuid.uuid4().hex[:12]
    now = utcnow()
    with _connect() as connection, connection:
        connection.execute(
            "INSERT INTO tariffs"
            "(id, name, description, preset_id, is_preset, config, created_at, updated_at) "
            "VALUES(?, ?, ?, ?, ?, ?, ?, ?)",
            (
                tariff_id,
                name,
                description,
                preset_id,
                1 if is_preset else 0,
                json.dumps(config, ensure_ascii=False),
                now,
                now,
            ),
        )
    result = get_tariff(tariff_id)
    assert result is not None
    return result


def update_tariff(
    tariff_id: str,
    name: str,
    description: str,
    config: dict[str, Any],
) -> dict[str, Any] | None:
    with _connect() as connection, connection:
        cursor = connection.execute(
            "UPDATE tariffs SET name = ?, description = ?, config = ?, updated_at = ? "
            "WHERE id = ?",
            (name, description, json.dumps(config, ensure_ascii=False), utcnow(), tariff_id),
        )
        if cursor.rowcount == 0:
            return None
    return get_tariff(tariff_id)


def delete_tariff(tariff_id: str) -> bool:
    with _connect() as connection, connection:
        cursor = connection.execute("DELETE FROM tariffs WHERE id = ?", (tariff_id,))
    return cursor.rowcount > 0


def duplicate_tariff(tariff_id: str) -> dict[str, Any] | None:
    original = get_tariff(tariff_id)
    if original is None:
        return None
    name = f"{original['name']} (kopia)"
    if len(name) > 80:
        name = name[:77] + "..."
    return create_tariff(
        name=name,
        description=original["description"],
        config=original["config"],
        preset_id=None,
        is_preset=False,
    )


def save_analysis(
    result: dict[str, Any],
    *,
    entity_id: str,
    entity_name: str,
) -> str:
    analysis_id = uuid.uuid4().hex
    cheapest = next(
        (
            item
            for item in result.get("tariffs", [])
            if item.get("tariff_id") == result.get("cheapest_tariff_id")
        ),
        None,
    )
    with _connect() as connection, connection:
        connection.execute(
            "INSERT INTO analyses"
            "(id, created_at, entity_id, entity_name, start, end, days, total_kwh, "
            "cheapest_name, cheapest_total_pln, max_savings_pln, result) "
            "VALUES(?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
            (
                analysis_id,
                utcnow(),
                entity_id,
                entity_name,
                result["start"],
                result["end"],
                int(result["days"]),
                float(result["total_kwh"]),
                cheapest["name"] if cheapest else None,
                cheapest["total_pln"] if cheapest else None,
                float(result.get("max_savings_pln") or 0),
                json.dumps(result, ensure_ascii=False),
            ),
        )
        connection.execute(
            "DELETE FROM analyses WHERE id NOT IN "
            "(SELECT id FROM analyses ORDER BY created_at DESC, rowid DESC LIMIT ?)",
            (MAX_ANALYSES,),
        )
    return analysis_id


def list_analyses(limit: int = 50) -> list[dict[str, Any]]:
    limit = max(1, min(int(limit), MAX_ANALYSES))
    with _connect() as connection:
        rows = connection.execute(
            "SELECT id, created_at, entity_id, entity_name, start, end, days, total_kwh, "
            "cheapest_name, cheapest_total_pln, max_savings_pln "
            "FROM analyses ORDER BY created_at DESC, rowid DESC LIMIT ?",
            (limit,),
        ).fetchall()
    return [dict(row) for row in rows]


def get_analysis(analysis_id: str) -> dict[str, Any] | None:
    with _connect() as connection:
        row = connection.execute(
            "SELECT * FROM analyses WHERE id = ?", (analysis_id,)
        ).fetchone()
    if row is None:
        return None
    try:
        result = json.loads(row["result"])
    except (TypeError, ValueError):
        result = None
    return {"id": row["id"], "created_at": row["created_at"], "result": result}


def delete_analysis(analysis_id: str) -> bool:
    with _connect() as connection, connection:
        cursor = connection.execute("DELETE FROM analyses WHERE id = ?", (analysis_id,))
    return cursor.rowcount > 0


def get_setting(key: str) -> str | None:
    with _connect() as connection:
        return _get_setting(connection, key)


def set_setting(key: str, value: str) -> None:
    with _connect() as connection, connection:
        _set_setting(connection, key, value)


def save_kompas(rows: list[dict[str, Any]], checkpoint: dict[str, str] | None = None) -> None:
    with _connect() as connection, connection:
        connection.executemany(
            'INSERT INTO kompas_hours(utc_hour,business_date,level,publication_utc) VALUES(?,?,?,?) '
            'ON CONFLICT(utc_hour) DO UPDATE SET level=excluded.level, publication_utc=excluded.publication_utc '
            'WHERE excluded.publication_utc >= kompas_hours.publication_utc',
            [(r['utc_hour'], r['business_date'], r['level'], r['publication_utc']) for r in rows])
        for key, value in (checkpoint or {}).items():
            _set_setting(connection, key, value)


def kompas_levels() -> dict[str, int]:
    with _connect() as connection:
        return {row['utc_hour']: row['level'] for row in connection.execute('SELECT utc_hour,level FROM kompas_hours')}


def kompas_level(utc_hour: str) -> int | None:
    with _connect() as connection:
        row = connection.execute('SELECT level FROM kompas_hours WHERE utc_hour=?', (utc_hour,)).fetchone()
        return row['level'] if row else None


def kompas_summary() -> dict[str, Any]:
    with _connect() as connection:
        row = connection.execute('SELECT COUNT(*) AS hours,MIN(business_date) AS first_day,MAX(business_date) AS last_day FROM kompas_hours').fetchone()
        return dict(row)


def kompas_gaps() -> list[dict[str, Any]]:
    """Missing archive hours, using 23/25-hour local days at DST changes."""
    from datetime import date, time, timedelta
    from .tariffs import TZ
    through = get_setting('kompas_history_through')
    if not through:
        return []
    with _connect() as connection:
        counts = {row['business_date']: row['hours'] for row in connection.execute(
            'SELECT business_date,COUNT(*) AS hours FROM kompas_hours WHERE business_date<=? GROUP BY business_date', (through,))}
    if not counts:
        return []
    day, end = date.fromisoformat(min(counts)), date.fromisoformat(through)
    result = []
    while day <= end:
        start = datetime.combine(day,time(),tzinfo=TZ).astimezone(timezone.utc)
        stop = datetime.combine(day+timedelta(days=1),time(),tzinfo=TZ).astimezone(timezone.utc)
        missing = int((stop-start).total_seconds()/3600) - counts.get(day.isoformat(),0)
        if missing:
            result.append({'day':day.isoformat(),'missing_hours':missing})
        day += timedelta(days=1)
    return result


def kompas_levels_between(start_utc: str, end_utc: str) -> dict[str, int]:
    with _connect() as connection:
        return {row['utc_hour']: row['level'] for row in connection.execute(
            'SELECT utc_hour,level FROM kompas_hours WHERE utc_hour>=? AND utc_hour<? ORDER BY utc_hour',
            (start_utc, end_utc))}


def save_export_prices(kind: str, rows: list[dict], checkpoint: dict | None = None) -> None:
    with _connect() as connection, connection:
        connection.executemany(
            'INSERT INTO export_prices(kind,stamp,price_mwh,publication) VALUES(?,?,?,?) '
            'ON CONFLICT(kind,stamp) DO UPDATE SET price_mwh=excluded.price_mwh,publication=excluded.publication '
            'WHERE excluded.publication >= export_prices.publication',
            [(kind, r['stamp'], r['price_mwh'], r['publication']) for r in rows])
        for key, value in (checkpoint or {}).items():
            _set_setting(connection, key, value)


def export_prices(kind: str, start: str, end: str) -> dict[str, float]:
    with _connect() as connection:
        return {r['stamp']: r['price_mwh'] for r in connection.execute(
            'SELECT stamp,price_mwh FROM export_prices WHERE kind=? AND stamp>=? AND stamp<?',
            (kind, start, end))}


def export_price_summary() -> list[dict]:
    with _connect() as connection:
        return [dict(r) for r in connection.execute(
            'SELECT kind,COUNT(*) AS count,MIN(stamp) AS first,MAX(stamp) AS last FROM export_prices GROUP BY kind')]
