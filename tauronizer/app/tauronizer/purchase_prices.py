"""Operator purchase prices. Separate from prosumer export RCE and Kompas zones."""
from __future__ import annotations

import asyncio
from datetime import date, datetime, time, timedelta, timezone
import logging
import math
from pathlib import Path
import ssl

import certifi

import httpx
from .tariffs import TZ, TariffValidationError

ENEA_API = 'https://www.enea.pl/api/enea-prices/individual/'
PGE_API = 'https://datahub.gkpge.pl/api/tge/quote'
LOGGER = logging.getLogger(__name__)


def source_for(config, day):
    source = config.get('energy_source', 'fixed')
    return ('pge_fix1' if day.year <= 2026 else 'pge_fix2') if source == 'pge_dynamic' else source


def day_hours(day):
    start = datetime.combine(day, time(), TZ).astimezone(timezone.utc)
    end = datetime.combine(day + timedelta(days=1), time(), TZ).astimezone(timezone.utc)
    return [start + timedelta(hours=i) for i in range(int((end-start).total_seconds()/3600))]


def parse_day(source, day, document):
    hours = day_hours(day)
    # Both feeds label hours with market wall-clock time. Neither currently
    # documents fold semantics. Reject DST transition days, never fabricate hours.
    if len(hours) != 24:
        raise ValueError(f'{day}: API nie określa jednoznacznie godzin w dniu zmiany czasu.')
    if not isinstance(document, list) or len(document) != 24:
        raise ValueError(f'{day}: niepełna doba cen operatora (oczekiwano 24 godzin).')
    prices = {}
    for row in document:
        if source == 'enea_dynamic':
            hour = int(row['hour']) - 1
            value = float(str(row['price']).replace(',', '.').replace('\xa0', '').replace(' ', ''))
        else:
            attrs = {item['name']: item['value'] for item in row['attributes']}
            expected = 'Fix_1' if source == 'pge_fix1' else 'Fix_2'
            if attrs['contract'] != expected:
                raise ValueError('PGE zwróciło inny fixing.')
            delivery = datetime.fromisoformat(attrs['quotationDate'])
            trading = datetime.fromisoformat(attrs['tradingDate'])
            # DataHub labels market wall-clock hours +00:00; cross-checked against
            # ENEA published retail prices. Do not shift this clock as UTC.
            if (delivery.date() != day or trading.date() != day - timedelta(days=1)
                    or delivery.utcoffset() != timedelta(0) or trading.utcoffset() != timedelta(0)
                    or delivery.minute or delivery.second or delivery.microsecond or trading.hour != delivery.hour):
                raise ValueError('Niezgodna data dostawy ceny PGE.')
            hour, value = delivery.hour, float(attrs['price']) / 1000
        if hour not in range(24) or hour in prices or not math.isfinite(value):
            raise ValueError('Nieprawidłowa lub powtórzona godzina/cena operatora.')
        prices[hour] = value
    return [dict(stamp=stamp.isoformat(), value=prices[hour]) for hour, stamp in enumerate(hours)]


def energy_prices(config, stamps):
    """Net energy excluding excise; same resolver for invoices and MQTT."""
    from . import db
    if config.get('energy_source', 'fixed') == 'fixed':
        return None
    stamps = list(stamps)
    if not stamps:
        return {}
    groups = {}
    for stamp in stamps:
        key = source_for(config, stamp.astimezone(TZ).date())
        groups.setdefault(key, []).append(stamp.astimezone(timezone.utc).replace(minute=0, second=0, microsecond=0))
    result = {}
    for source, hours in groups.items():
        values = db.purchase_prices(source, min(hours).isoformat(), (max(hours) + timedelta(hours=1)).isoformat())
        for stamp in hours:
            raw = values.get(stamp.isoformat())
            if raw is None:
                raise TariffValidationError(f'Brak ceny zakupu {source} na {stamp.astimezone(TZ):%d.%m.%Y %H:%M %z}. Uzupełnij dane cen w zakładce Taryfy. Braki nie są zastępowane zerem.')
            # ENEA publishes retail gross inclusive of excise and margin.
            # PGE publishes market net, with contractual floor/cap and markup.
            value = (raw / 1.23 - .005) if source == 'enea_dynamic' else min(4, max(0, raw)) + float(config.get('energy_markup_net', .0855))
            result[stamp.isoformat()] = value
    return result


def energy_price(config, zone, stamp):
    values = energy_prices(config, [stamp])
    key = stamp.astimezone(timezone.utc).replace(minute=0, second=0, microsecond=0).isoformat()
    return zone.energy_net if values is None else values[key]


class PurchasePriceCache:
    def __init__(self, on_update=None):
        # PGE currently omits this intermediate from its TLS chain. Supplement
        # chain building, retaining default root trust, hostname and expiry checks.
        context = ssl.create_default_context(cafile=certifi.where())
        context.load_verify_locations(str(Path(__file__).with_name('certs') / 'certum-dv-tls-g2-r39.pem'))
        context.verify_flags &= ~ssl.VERIFY_X509_PARTIAL_CHAIN
        self.http = httpx.AsyncClient(timeout=30, follow_redirects=True, verify=context,
            headers={'User-Agent': 'Tauronizer (+https://github.com/direk/tauronizer)'})
        self.lock = asyncio.Lock()
        self.wake = asyncio.Event()
        self.on_update = on_update
        self.status, self.error = 'waiting', None

    async def close(self):
        await self.http.aclose()

    def snapshot(self):
        from . import db
        return dict(status=self.status, error=self.error, last_update=db.get_setting('purchase_prices_updated'),
                    series=db.purchase_price_summary(), sources=[ENEA_API, PGE_API])

    async def day(self, source, day, refresh=False):
        from . import db
        if day < date(2024, 8, 22):
            raise ValueError('Archiwum cen zakupu jest dostępne od 22.08.2024; wcześniejszych cen nie estymujemy.')
        async with self.lock:
            hours = day_hours(day)
            if not refresh and len(db.purchase_prices(source, hours[0].isoformat(), (hours[-1]+timedelta(hours=1)).isoformat())) == len(hours):
                return
            if source == 'enea_dynamic':
                response = await self.http.get(ENEA_API + day.strftime('%d.%m.%Y'))
            else:
                trading = day - timedelta(days=1)
                response = await self.http.get(PGE_API, params=dict(source='TGE', contract='Fix_1' if source == 'pge_fix1' else 'Fix_2',
                    date_from=f'{trading} 00:00:00', date_to=f'{trading} 23:59:59', limit=100))
            response.raise_for_status()
            rows = parse_day(source, day, response.json())
            db.save_purchase_prices(source, rows)
            if self.on_update:
                self.on_update.set()

    async def ensure(self, tariffs, start, end, *, reverse=False):
        """Fill only gaps; a source/day is shared by all tariffs and analyses."""
        if not any(t['config'].get('energy_source', 'fixed') != 'fixed' for t in tariffs):
            return
        failures = []
        first = max(start, date(2024, 8, 22))
        cursor = end if reverse else first
        failed_sources = set()
        while first <= cursor <= end:
            sources = {source_for(t['config'], cursor) for t in tariffs} - {'fixed'}
            for source in sorted(sources - failed_sources):
                try:
                    await self.day(source, cursor)
                except (httpx.HTTPError, ValueError, KeyError, TypeError) as exc:
                    failures.append(f'{source}: {exc}')
                    # A failed day stays missing. Continue after DST only, avoid
                    # thousands of retries during an outage or unpublished history.
                    if len(day_hours(cursor)) == 24:
                        failed_sources.add(source)
            cursor += timedelta(days=-1 if reverse else 1)
        self.error = '; '.join(failures[-3:]) or None
        self.status = 'error' if failures else 'ready'

    async def sync(self):
        from . import db
        tariffs = [t for t in db.list_tariffs() if t['config'].get('energy_source', 'fixed') != 'fixed']
        if not tariffs:
            self.status, self.error = 'idle', None
            return
        self.status = 'syncing'
        today = datetime.now(TZ).date()
        errors = []
        # Latest prices first, including tomorrow. Old complete days are immutable.
        for day in (today, today + timedelta(days=1)):
            for source in sorted({source_for(t['config'], day) for t in tariffs}):
                try:
                    await self.day(source, day, refresh=True)
                except Exception as exc:
                    errors.append(f'{source}: {exc}')
        await self.ensure(tariffs, date(2024, 8, 22), today - timedelta(days=1), reverse=True)
        if errors:
            self.error = '; '.join(errors)
            self.status = 'error'

    async def run(self):
        while True:
            self.wake.clear()
            try:
                await self.sync()
            except Exception as exc:
                self.status, self.error = 'error', str(exc)
                LOGGER.warning('Purchase price sync: %s', exc)
            try:
                await asyncio.wait_for(self.wake.wait(), timeout=3600 if self.status in ('ready', 'idle') else 300)
            except asyncio.TimeoutError:
                pass
