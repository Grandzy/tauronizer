"""Persistent official PSE Kompas history; analysis never downloads this data."""
from __future__ import annotations

import asyncio
from datetime import date, datetime, timedelta, timezone
import logging
from urllib.parse import urlparse
import httpx

from .db import get_setting, set_setting, save_kompas, kompas_summary, kompas_gaps
from .tariffs import TZ

API = 'https://api.raporty.pse.pl/api/pdgsz'
_LOGGER = logging.getLogger(__name__)


def utc_key(instant: datetime) -> str:
    if instant.tzinfo is None:
        raise ValueError('Wymagany czas ze strefą.')
    return instant.astimezone(timezone.utc).replace(minute=0, second=0, microsecond=0).isoformat()


def parse_rows(document: object) -> list[dict]:
    if not isinstance(document, dict) or not isinstance(document.get('value'), list):
        raise ValueError('Nieprawidłowy format odpowiedzi Kompasu PSE.')
    result = {}
    for row in document['value']:
        if not isinstance(row, dict):
            raise ValueError('Nieprawidłowy rekord Kompasu PSE.')
        if row.get('is_active') is not True:
            continue
        level = row.get('usage_fcst')
        if type(level) is not int or level not in range(4):
            raise ValueError('Nieznany poziom Kompasu PSE.')
        instant = datetime.fromisoformat(row['dtime_utc'])
        instant = instant.replace(tzinfo=timezone.utc) if instant.tzinfo is None else instant.astimezone(timezone.utc)
        if instant.minute or instant.second:
            raise ValueError('Kompas nie zwrócił danych godzinowych.')
        day = date.fromisoformat(row['business_date'])
        if instant.astimezone(TZ).date() != day:
            raise ValueError('Niezgodna data handlowa Kompasu PSE.')
        publication_dt = datetime.fromisoformat(row['publication_ts_utc'])
        publication = (publication_dt.replace(tzinfo=timezone.utc) if publication_dt.tzinfo is None else publication_dt.astimezone(timezone.utc)).isoformat()
        key = utc_key(instant)
        previous = result.get(key)
        record = dict(utc_hour=key, business_date=day.isoformat(), level=level, publication_utc=publication)
        if previous and previous['publication_utc'] == publication and previous['level'] != level:
            raise ValueError('Sprzeczne strefy Kompasu PSE.')
        if not previous or publication >= previous['publication_utc']:
            result[key] = record
    return list(result.values())


def valid_url(value: str) -> str:
    parsed = urlparse(value)
    if parsed.scheme != 'https' or parsed.netloc != 'api.raporty.pse.pl' or parsed.path != '/api/pdgsz':
        raise ValueError('Nieprawidłowy adres kolejnej strony PSE.')
    return value


class KompasCache:
    def __init__(self, notify=None):
        self.notify = notify
        self.wake = asyncio.Event()
        self.status = 'ready' if get_setting('kompas_last_sync') and not get_setting('kompas_history_next') else 'waiting'
        self.error = None
        self.http = httpx.AsyncClient(timeout=30.0, follow_redirects=False)

    def snapshot(self):
        gaps = kompas_gaps()
        return {**kompas_summary(), 'missing_archive_hours': sum(day['missing_hours'] for day in gaps), 'status': self.status, 'error': self.error,
                'last_sync': get_setting('kompas_last_sync'),
                'history_through': get_setting('kompas_history_through'),
                'source': API}

    async def document(self, url):
        response = await self.http.get(valid_url(url))
        response.raise_for_status()
        return response.json()

    def query(self, start, end):
        return str(httpx.URL(API, params={
            '$filter': f"business_date ge '{start}' and business_date le '{end}' and is_active eq true",
            '$orderby': 'dtime_utc asc', '$first': '1000'}))

    async def pages(self, url, *, archive_target=None):
        seen = set()
        for _ in range(10000):
            if url in seen:
                raise ValueError('Powtarzająca się strona Kompasu PSE.')
            seen.add(url)
            document = await self.document(url)
            rows = parse_rows(document)
            next_url = document.get('nextLink') or document.get('@odata.nextLink') or ''
            if next_url:
                valid_url(next_url)
            checkpoint = {}
            if archive_target:
                checkpoint['kompas_history_next'] = next_url
                if not next_url:
                    checkpoint['kompas_history_through'] = archive_target
                    checkpoint['kompas_history_target'] = ''
            save_kompas(rows, checkpoint)
            if self.notify:
                self.notify.set()
            if not next_url:
                return
            url = next_url
            await asyncio.sleep(0)  # allow shutdown and API traffic between durable pages
        raise ValueError('Przekroczono limit stron Kompasu PSE.')

    async def sync(self):
        today = datetime.now(TZ).date()
        self.error = None
        self.status = 'updating'
        await self.pages(self.query(today - timedelta(days=2), today + timedelta(days=1)))
        self.status = 'importing'
        cursor = get_setting('kompas_history_next')
        target = get_setting('kompas_history_target')
        if cursor and target:
            await self.pages(cursor, archive_target=target)
        through = get_setting('kompas_history_through')
        yesterday = today - timedelta(days=1)
        if not through:
            first_query = str(httpx.URL(API, params={'$filter': 'is_active eq true', '$orderby': 'dtime_utc asc', '$first': '1'}))
            rows = parse_rows(await self.document(first_query))
            if not rows:
                raise ValueError('PSE nie zwróciło początku historii Kompasu.')
            start = date.fromisoformat(rows[0]['business_date'])
        else:
            start = date.fromisoformat(through) + timedelta(days=1)
        if start <= yesterday:
            url = self.query(start, yesterday)
            # Persist the fixed import horizon so restarts never skip an unfinished page.
            set_setting('kompas_history_target', yesterday.isoformat())
            set_setting('kompas_history_next', url)
            await self.pages(url, archive_target=yesterday.isoformat())
        gaps = kompas_gaps()
        if gaps:
            # Retry a bounded, rotating batch; never redownload the complete archive.
            cursor = int(get_setting('kompas_gap_cursor') or 0) % len(gaps)
            for index in range(min(7, len(gaps))):
                day = gaps[(cursor + index) % len(gaps)]['day']
                await self.pages(self.query(day, day))
            set_setting('kompas_gap_cursor', str(cursor + min(7, len(gaps))))
        set_setting('kompas_last_sync', datetime.now(timezone.utc).isoformat())
        self.status = 'ready'

    async def run(self):
        while True:
            self.wake.clear()
            try:
                await self.sync()
            except Exception:
                self.status = 'error'
                self.error = 'Nie udało się uzupełnić Kompasu PSE. Zachowano pobrane dane; import będzie wznowiony.'
                _LOGGER.warning('Kompas PSE update failed; cached data and checkpoint retained.')
            try:
                await asyncio.wait_for(self.wake.wait(), timeout=900 if self.status == 'ready' else 60)
            except TimeoutError:
                pass

    async def close(self):
        await self.http.aclose()
