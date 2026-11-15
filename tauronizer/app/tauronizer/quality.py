"""Coverage of completed hourly consumption statistics, counted in UTC."""
from __future__ import annotations

from calendar import monthrange
from datetime import date, datetime, time, timedelta, timezone
import math

from .tariffs import TZ


def consumption_coverage(samples, start_date: date, end_date: date, now=None):
    now = (now or datetime.now(timezone.utc)).astimezone(timezone.utc)
    start = datetime.combine(start_date, time.min, TZ).astimezone(timezone.utc)
    end = datetime.combine(end_date + timedelta(days=1), time.min, TZ).astimezone(timezone.utc)
    cutoff = min(end, now.replace(minute=0, second=0, microsecond=0))
    cutoff = max(start, cutoff)
    observed = set()
    invalid = duplicates = 0
    for sample in samples:
        stamp = sample.timestamp.astimezone(timezone.utc)
        if not start <= stamp < cutoff:
            continue
        if stamp.minute or stamp.second or stamp.microsecond or not math.isfinite(sample.kwh) or sample.kwh < 0:
            invalid += 1
            continue
        if stamp in observed:
            duplicates += 1
        observed.add(stamp)
    months = {}
    day = start_date.replace(day=1)
    while day <= end_date:
        key = day.strftime('%Y-%m')
        months[key] = {'month': key, 'expected_hours': 0, 'received_hours': 0, 'pending_hours': 0,
                       'partial_month': start_date > day or end_date < day.replace(day=monthrange(day.year, day.month)[1])}
        day = (day.replace(day=28) + timedelta(days=4)).replace(day=1)
    gaps = []
    gap_start = None
    gap_count = 0
    cursor = start
    expected = received = 0
    def close_gap(stop):
        nonlocal gap_start, gap_count
        if gap_start is not None:
            gap_count += 1
            if len(gaps) < 200:
                gaps.append({'start': gap_start.isoformat(), 'end': stop.isoformat(),
                             'hours': int((stop - gap_start).total_seconds() / 3600)})
            gap_start = None
    while cursor < end:
        row = months[cursor.astimezone(TZ).strftime('%Y-%m')]
        if cursor >= cutoff:
            row['pending_hours'] += 1
        else:
            expected += 1
            row['expected_hours'] += 1
            if cursor in observed:
                received += 1
                row['received_hours'] += 1
                close_gap(cursor)
            elif gap_start is None:
                gap_start = cursor
        cursor += timedelta(hours=1)
    close_gap(cutoff)
    def summarize(row):
        row['missing_hours'] = row['expected_hours'] - row['received_hours']
        row['complete'] = row['missing_hours'] == 0 and row['expected_hours'] > 0
        percent = round(row['received_hours'] / row['expected_hours'] * 100, 2) if row['expected_hours'] else None
        row['percent'] = min(percent, 99.99) if row['missing_hours'] and percent is not None else percent
        return row
    result = summarize({'expected_hours': expected, 'received_hours': received})
    return {**result, 'pending_hours': sum(row['pending_hours'] for row in months.values()),
            'months': [summarize(row) for row in months.values()], 'gaps': gaps,
            'gap_count': gap_count, 'gaps_truncated': gap_count > len(gaps),
            'invalid_samples': invalid, 'duplicate_samples': duplicates, 'checked_at': now.isoformat(),
            'counted_until': cutoff.isoformat()}
