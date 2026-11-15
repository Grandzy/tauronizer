"""Published Kompas schedule; missing hours never imply a tariff zone."""
from __future__ import annotations

from datetime import datetime, time, timedelta, timezone

from .db import kompas_levels_between
from .kompas import utc_key
from .tariffs import TZ, compile_zones


def dynamic_schedule(tariff, now=None):
    now = (now or datetime.now(timezone.utc)).astimezone(timezone.utc)
    if not tariff or tariff['config'].get('zone_source') != 'pse_kompas':
        return {'tariff_id': tariff['id'] if tariff else None, 'tariff_name': tariff['name'] if tariff else None,
                'days': [], 'next_change': None, 'reason': 'Wybierz taryfę G14dynamic w Sensorach.'}
    zones = {zone.kompas_level: zone for zone in compile_zones(tariff['config'])}
    today = now.astimezone(TZ).date()
    start = datetime.combine(today, time.min, TZ).astimezone(timezone.utc)
    end = datetime.combine(today + timedelta(days=2), time.min, TZ).astimezone(timezone.utc)
    levels = kompas_levels_between(start.isoformat(), end.isoformat())
    config = tariff['config']
    extra = sum(float(fee.get('net_per_kwh', 0) or 0) for fee in config.get('variable_fees') or []) + float(config.get('excise_net_per_kwh', 0) or 0)
    vat = 1 + float(config.get('vat_percent', 23) or 0) / 100
    days = []
    hours = []
    for offset in (0, 1):
        day = today + timedelta(days=offset)
        cursor = datetime.combine(day, time.min, TZ).astimezone(timezone.utc)
        stop = datetime.combine(day + timedelta(days=1), time.min, TZ).astimezone(timezone.utc)
        segments = []
        available = total = 0
        while cursor < stop:
            zone = zones.get(levels.get(utc_key(cursor)))
            total += 1
            available += zone is not None
            hour = {'start': cursor.isoformat(), 'end': (cursor + timedelta(hours=1)).isoformat(),
                    'level': zone.kompas_level if zone else None,
                    'zone_id': zone.id if zone else None, 'zone_name': zone.name if zone else None,
                    'price_gross': round((zone.energy_net + zone.distribution_net + extra) * vat, 6) if zone else None}
            hours.append(hour)
            if segments and segments[-1]['level'] == hour['level']:
                segments[-1]['end'] = hour['end']
            else:
                segments.append(dict(hour))
            cursor += timedelta(hours=1)
        days.append({'date': day.isoformat(), 'expected_hours': total, 'available_hours': available,
                     'complete': available == total, 'segments': segments})
    current_index = next(i for i, hour in enumerate(hours) if hour['start'] == utc_key(now))
    current = hours[current_index]
    next_change = None
    reason = 'Nie opublikowano kolejnej zmiany w dostępnym harmonogramie.'
    if current['level'] is None:
        reason = 'Brak danych Kompasu dla aktualnej godziny.'
    else:
        for hour in hours[current_index + 1:]:
            if hour['level'] is None:
                reason = 'Brak ciągłych danych Kompasu do następnej zmiany.'
                break
            if hour['level'] != current['level']:
                next_change = {'at': hour['start'], 'zone_name': hour['zone_name'],
                               'zone_id': hour['zone_id'], 'level': hour['level'], 'price_gross': hour['price_gross']}
                reason = None
                break
    return {'tariff_id': tariff['id'], 'tariff_name': tariff['name'], 'days': days,
            'next_change': next_change, 'reason': reason, 'generated_at': now.isoformat()}
