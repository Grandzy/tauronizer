"""Persistent PSE export prices, independent from G14 Kompas distribution zones."""
from __future__ import annotations

import asyncio
from datetime import date, datetime, timedelta, timezone
from html.parser import HTMLParser
import logging
import math
import re
from urllib.parse import urlparse

import httpx
from . import db
from .tariffs import TZ

RCE_API = 'https://api.raporty.pse.pl/api/rce-pln'
RCEM_URL = 'https://www.pse.pl/oire/rcem-rynkowa-miesieczna-cena-energii-elektrycznej'
LOGGER = logging.getLogger(__name__)
MONTHS = ['styczeń', 'luty', 'marzec', 'kwiecień', 'maj', 'czerwiec', 'lipiec',
          'sierpień', 'wrzesień', 'październik', 'listopad', 'grudzień']


def next_month(day: date) -> date:
    return (day.replace(day=28) + timedelta(days=4)).replace(day=1)


def parse_rce(document: object) -> list[dict]:
    if not isinstance(document, dict) or not isinstance(document.get('value'), list):
        raise ValueError('Nieprawidłowa odpowiedź cen RCE PSE.')
    rows = []
    for row in document['value']:
        # PSE dtime is the END of a 15-minute period (including 24:00).
        end = datetime.fromisoformat(row['dtime_utc']).replace(tzinfo=timezone.utc)
        publication = datetime.fromisoformat(row['publication_ts_utc']).replace(tzinfo=timezone.utc)
        price = float(row['rce_pln'])
        if end.second or end.microsecond or end.minute % 15 or not math.isfinite(price):
            raise ValueError('Nieprawidłowy okres lub cena RCE.')
        start = end - timedelta(minutes=15)
        if start.astimezone(TZ).date().isoformat() != row['business_date']:
            raise ValueError('Niezgodna data handlowa RCE.')
        rows.append(dict(stamp=start.isoformat(), price_mwh=price, publication=publication.isoformat()))
    return rows


class _TableParser(HTMLParser):
    def __init__(self):
        super().__init__()
        self.rows, self.row, self.cell = [], None, None

    def handle_starttag(self, tag, attrs):
        if tag == 'tr':
            self.row = []
        elif tag in ('td', 'th') and self.row is not None:
            self.cell = ''

    def handle_data(self, data):
        if self.cell is not None:
            self.cell += data

    def handle_endtag(self, tag):
        if tag in ('td', 'th') and self.cell is not None:
            self.row.append(' '.join(self.cell.split()))
            self.cell = None
        elif tag == 'tr' and self.row is not None:
            self.rows.append(self.row)
            self.row = None


def parse_rcem(html: str) -> list[dict]:
    parser = _TableParser()
    parser.feed(html)
    year = month = None
    rows = {}
    for cells in parser.rows:
        if len(cells) == 1 and re.fullmatch(r'20\d{2}', cells[0]):
            year, month = int(cells[0]), None
        elif len(cells) == 1 and cells[0].lower() in MONTHS:
            month = MONTHS.index(cells[0].lower()) + 1
        elif year and month and len(cells) >= 3 and 'RCEm' in cells[0]:
            if cells[1] == '-' or cells[2] == '-':
                continue
            price = float(cells[1].replace(' ', '').replace(',', '.'))
            publication = datetime.strptime(cells[2], '%d.%m.%Y').date().isoformat()
            if not math.isfinite(price):
                raise ValueError('Nieprawidłowa cena RCEm.')
            key = f'{year:04d}-{month:02d}'
            if key not in rows or publication >= rows[key]['publication']:
                rows[key] = dict(stamp=key, price_mwh=price, publication=publication)
    if not rows:
        raise ValueError('Nie rozpoznano tabeli RCEm PSE. Zachowano poprzednie ceny.')
    return list(rows.values())


class ExportPriceCache:
    def __init__(self):
        self.http = httpx.AsyncClient(timeout=30, follow_redirects=False)
        self.lock = asyncio.Lock()
        self.status = 'waiting'
        self.error = None
        self.wake = asyncio.Event()

    def snapshot(self):
        return dict(status=self.status, error=self.error, last_update=db.get_setting('export_prices_updated'),
                    series=db.export_price_summary(), rce_source=RCE_API, rcem_source=RCEM_URL)

    async def close(self):
        await self.http.aclose()

    async def rcem(self):
        response = await self.http.get(RCEM_URL)
        response.raise_for_status()
        db.save_export_prices('rcem', parse_rcem(response.text), {'export_prices_updated': db.utcnow()})

    async def month(self, month: date, refresh=False):
        key = f'rce_month_{month:%Y-%m}'
        async with self.lock:
            checkpoint = db.get_setting(key)
            if checkpoint == 'done' and not refresh:
                return
            after = next_month(month)
            url = checkpoint if checkpoint and checkpoint != 'done' else (
                f"{RCE_API}?$filter=business_date ge '{month}' and business_date lt '{after}'&$first=10000")
            seen = set()
            for _ in range(100):
                parsed = urlparse(url)
                if parsed.scheme != 'https' or parsed.netloc != 'api.raporty.pse.pl' or parsed.path != '/api/rce-pln' or url in seen:
                    raise ValueError('Nieprawidłowa paginacja cen RCE PSE.')
                seen.add(url)
                response = await self.http.get(url)
                response.raise_for_status()
                doc = response.json()
                rows = parse_rce(doc)
                if any(not (month <= datetime.fromisoformat(r['stamp']).astimezone(TZ).date() < after) for r in rows):
                    raise ValueError('PSE zwróciło ceny spoza żądanego miesiąca.')
                following = doc.get('nextLink') or doc.get('@odata.nextLink')
                # Empty / unpublished months must be retried rather than cached as complete.
                db.save_export_prices('rce', rows, {key: following or '', 'export_prices_updated': db.utcnow()})
                if not following:
                    start_utc = datetime.combine(max(month, date(2024,6,14)), datetime.min.time(), tzinfo=TZ).astimezone(timezone.utc)
                    end_utc = datetime.combine(after, datetime.min.time(), tzinfo=TZ).astimezone(timezone.utc)
                    expected = int((end_utc-start_utc).total_seconds()/900)
                    cached = db.export_prices('rce', start_utc.isoformat(), end_utc.isoformat())
                    if expected > 0 and len(cached) == expected:
                        db.set_setting(key, 'done')
                    return
                url = following
            raise ValueError('Zbyt wiele stron cen RCE.')

    async def ensure(self, mode: str, start: date, end: date):
        if mode == 'rcem':
            # One HTML document contains the full official archive and corrections.
            months = db.export_prices('rcem', start.strftime('%Y-%m'), next_month(end.replace(day=1)).strftime('%Y-%m'))
            cursor = start.replace(day=1)
            missing = False
            while cursor <= end:
                missing |= cursor.strftime('%Y-%m') not in months
                cursor = next_month(cursor)
            if missing:
                async with self.lock:
                    await self.rcem()
        elif mode == 'rce':
            cursor = max(start.replace(day=1), date(2024, 6, 1))
            while cursor <= end:
                await self.month(cursor)
                cursor = next_month(cursor)

    async def sync(self):
        self.status, self.error = 'syncing', None
        try:
            async with self.lock:
                await self.rcem()
            today = datetime.now(TZ).date()
            recent = (today.replace(day=1) - timedelta(days=90)).replace(day=1)
            cursor = recent
            while cursor <= today:
                await self.month(cursor, refresh=True)
                cursor = next_month(cursor)
            cursor = date(2024, 6, 1)
            while cursor < recent:
                await self.month(cursor)
                cursor = next_month(cursor)
            db.set_setting('export_prices_updated', db.utcnow())
            self.status = 'ready'
        except Exception as exc:
            self.status, self.error = 'error', str(exc)
            LOGGER.warning('Export price sync: %s', exc)

    async def run(self):
        while True:
            await self.sync()
            self.wake.clear()
            try:
                await asyncio.wait_for(self.wake.wait(), timeout=3600 if self.status == 'ready' else 300)
            except asyncio.TimeoutError:
                pass
