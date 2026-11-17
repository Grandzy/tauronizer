"""Monthly comparative prosumer simulation; balances are never treated as cash income."""
from __future__ import annotations

import copy
import math
from collections import defaultdict
from datetime import date, datetime, timedelta, timezone
from . import db
from .calc import ConsumptionSample, _cost_for_tariff, _round
from .export_prices import next_month
from .tariffs import TZ, zone_for


def add_months(month: str, count: int) -> str:
    year, number = map(int, month.split('-'))
    index = year * 12 + number - 1 + count
    return f'{index // 12:04d}-{index % 12 + 1:02d}'


def clean_hours(samples):
    result = {}
    for sample in samples:
        stamp = sample.timestamp.astimezone(timezone.utc)
        if math.isfinite(sample.kwh) and sample.kwh >= 0 and not (stamp.minute or stamp.second or stamp.microsecond):
            result[stamp] = sample.kwh
    return result


def paired_energy(import_samples, export_samples):
    """Only jointly measured hours, with vector balancing within the hour."""
    imports, exports = clean_hours(import_samples), clean_hours(export_samples)
    common = sorted(imports.keys() & exports.keys())
    return ([ConsumptionSample(t, max(0, imports[t] - exports[t])) for t in common],
            [ConsumptionSample(t, max(0, exports[t] - imports[t])) for t in common])


class ProsumerCalculation:
    def __init__(self, settings, samples, exports, start, end):
        self.settings, self.samples, self.exports = settings, samples, exports
        self.start, self.end = start, end
        self.cache = {}
        self.export_months = defaultdict(list)
        for sample in exports:
            self.export_months[sample.timestamp.astimezone(TZ).strftime('%Y-%m')].append(sample)
        self.rcem = db.export_prices('rcem', start.strftime('%Y-%m'), add_months(end.strftime('%Y-%m'), 1)) if settings.mode == 'rcem' else {}
        self.rce = db.export_prices('rce',
            datetime.combine(start, datetime.min.time(), tzinfo=TZ).astimezone(timezone.utc).isoformat(),
            datetime.combine(end + timedelta(days=1), datetime.min.time(), tzinfo=TZ).astimezone(timezone.utc).isoformat()) if settings.mode == 'rce' else {}

    def export_value(self, month):
        samples = self.export_months[month]
        if self.settings.mode == 'rcem':
            kwh = sum(s.kwh for s in samples)
            if kwh and month not in self.rcem:
                raise ValueError(f'Brak opublikowanej ceny RCEm za {month}.')
            return kwh * max(0, self.rcem.get(month, 0)) / 1000
        value = 0
        for sample in samples:
            if sample.kwh == 0:
                continue
            # Equal allocation into the four quarters is explicit in methodology.
            keys = [(sample.timestamp.astimezone(timezone.utc) + timedelta(minutes=i*15)).isoformat() for i in range(4)]
            if any(k not in self.rce for k in keys):
                raise ValueError(f'Brak kompletu cen RCE dla {sample.timestamp.isoformat()}.')
            value += sample.kwh * sum(max(0, self.rce[k]) for k in keys) / 4000
        return value

    def calculate(self, tariff, zones, holidays, levels):
        if tariff['id'] in self.cache:
            return self.cache[tariff['id']]
        mode = self.settings.mode
        metering = mode == 'net_metering'
        first_month = self.start.strftime('%Y-%m')
        lots = []
        for opening in self.settings.opening_balances:
            if opening.month > first_month or (metering and opening.month == first_month):
                raise ValueError('Saldo początkowe nie może pochodzić z przyszłych miesięcy; w opustach miesiąc eksportu musi poprzedzać miesiąc analizy.')
            if metering and opening.zone_id and opening.zone_id not in {z.id for z in zones}:
                raise ValueError(f'Strefa salda „{opening.zone_id}” nie istnieje w tej taryfie.')
            lots.append(dict(available=opening.month, expiry=add_months(opening.month, 13 if metering else 12),
                             amount=opening.amount, zone=opening.zone_id,
                             refund_cap=None if opening.export_value_pln is None else opening.export_value_pln * (.3 if mode == 'rce' and opening.month >= '2025-03' else .2)))
        input_by_month = defaultdict(list)
        for sample in self.samples:
            local = sample.timestamp.astimezone(TZ)
            input_by_month[local.strftime('%Y-%m')].append((local, sample.kwh))
        months = {}
        cursor = self.start.replace(day=1)
        basis = (sum(s.kwh for s in self.samples), (self.end-self.start).days+1)
        aggregate = None
        ledger = []
        while cursor <= self.end:
            month = cursor.strftime('%Y-%m')
            following = next_month(cursor)
            days = (min(self.end + timedelta(days=1), following) - max(self.start, cursor)).days
            expired = sum(l['amount'] for l in lots if l['expiry'] <= month)
            refundable = sum(min(l['amount'], l['refund_cap']) for l in lots if l['expiry'] <= month and l['refund_cap'] is not None) if not metering else 0
            unknown_refund = any(l['amount'] > 0 and l['refund_cap'] is None for l in lots if l['expiry'] <= month) if not metering else False
            lots = [l for l in lots if l['expiry'] > month]
            local_samples = input_by_month[month]
            total = sum(k for _, k in local_samples)
            if not local_samples:
                raise ValueError(f'Brak wspólnych statystyk poboru i eksportu w {month}; nie można kontynuować salda.')
            export_kwh = sum(s.kwh for s in self.export_months[month])
            gross = _cost_for_tariff(tariff, zones, local_samples, holidays, total, days, levels, basis)
            used, created, export_value = 0, 0, 0
            if metering:
                export_zones = defaultdict(float)
                for sample in self.export_months[month]:
                    zone = zone_for(sample.timestamp.astimezone(TZ), zones, holidays, levels)
                    export_zones[zone.id] += sample.kwh * self.settings.ratio
                for zone, amount in export_zones.items():
                    lots.append(dict(available=month, expiry=add_months(month, 13), amount=amount, zone=zone, refund_cap=0))
                created = sum(export_zones.values())
                assigned = [(t, k, zone_for(t, zones, holidays, levels).id) for t, k in local_samples]
                raw_totals = {z.id: 0.0 for z in zones}
                for _, kwh, zone_id in assigned:
                    raw_totals[zone_id] += kwh
                needs = raw_totals.copy()
                lots.sort(key=lambda l: (l['expiry'], l['available']))
                def consume(zone, same):
                    nonlocal used
                    for lot in lots:
                        if lot['available'] <= month and (not same or lot['zone'] == zone):
                            amount = min(needs[zone], lot['amount'])
                            needs[zone] -= amount
                            lot['amount'] -= amount
                            used += amount
                # Match ALL original zones before moving leftovers to the most expensive distribution zone.
                for zone in zones:
                    consume(zone.id, True)
                for zone in sorted(zones, key=lambda z: z.distribution_net, reverse=True):
                    consume(zone.id, False)
                # Use unrounded denominators to avoid creating/losing energy.
                residual = [(t, k * needs[zone_id] / raw_totals[zone_id])
                            for t, k, zone_id in assigned if k > 0]
                cost = _cost_for_tariff(tariff,zones,residual,holidays,sum(needs.values()),days,levels,basis)
                credit_used = gross['total_pln'] - cost['total_pln']
            else:
                export_value = self.export_value(month)
                created = _round(export_value * (1.23 if month >= '2025-02' else 1))
                lots.append(dict(available=add_months(month,1), expiry=add_months(month,13), amount=created,
                                 zone=None, refund_cap=export_value*(.3 if mode=='rce' and month>='2025-02' else .2)))
                vat = 1 + tariff['config'].get('vat_percent',23)/100
                eligible = _round((gross['breakdown']['energy_pln'] + gross['breakdown']['excise_pln']) * vat)
                for lot in sorted(lots, key=lambda l: (l['expiry'], l['available'])):
                    if lot['available'] <= month:
                        amount = min(max(0, eligible-used), lot['amount'])
                        lot['amount'] -= amount
                        used += amount
                cost = gross
                credit_used = _round(used)
                cost = {**cost, 'total_pln': _round(max(0,gross['total_pln'] - credit_used))}
            lots = [l for l in lots if l['amount'] > 1e-9]
            row = dict(month=month, import_kwh=_round(total,3), export_kwh=_round(export_kwh,3),
                       purchase_gross_pln=gross['total_pln'], export_value_pln=_round(export_value),
                       credit_created=_round(created,3 if metering else 2), credit_used=_round(used,3 if metering else 2),
                       credit_used_pln=_round(credit_used), due_pln=cost['total_pln'],
                       balance=_round(sum(l['amount'] for l in lots),3 if metering else 2),
                       expired=_round(expired,3 if metering else 2), refundable_pln=_round(refundable), refund_unknown=unknown_refund)
            ledger.append(row)
            months[month] = cost
            if aggregate is None:
                aggregate = copy.deepcopy(cost)
            else:
                aggregate['total_pln'] += cost['total_pln']
                for key,val in cost['breakdown'].items():
                    if key != 'invoice_items': aggregate['breakdown'][key] += val
                for a,b in zip(aggregate['breakdown']['invoice_items'],cost['breakdown']['invoice_items']):
                    a['amount_pln'] += b['amount_pln']
                for a,b in zip(aggregate['zones'],cost['zones']):
                    for key in ('kwh','energy_pln','distribution_pln'): a[key] += b[key]
            cursor = following
        aggregate['total_pln'] = _round(aggregate['total_pln'])
        aggregate['annual_pln'] = _round(aggregate['total_pln'] * 365.25 / basis[1])
        aggregate['per_kwh_pln'] = _round(aggregate['total_pln']/basis[0],4) if basis[0] else 0
        zone_total = sum(z['kwh'] for z in aggregate['zones'])
        for zone in aggregate['zones']:
            zone['share_percent'] = _round(zone['kwh']/zone_total*100,1) if zone_total else 0
        aggregate['prosumer'] = dict(mode=mode, unit='kWh' if metering else 'zł', months=ledger,
            purchase_gross_pln=_round(sum(r['purchase_gross_pln'] for r in ledger)),
            credit_used_pln=_round(sum(r['credit_used_pln'] for r in ledger)), closing_balance=ledger[-1]['balance'],
            expired=_round(sum(r['expired'] for r in ledger),3 if metering else 2),
            refundable_pln=_round(sum(r['refundable_pln'] for r in ledger)),
            closing_lots=lots)
        self.cache[tariff['id']] = aggregate, months
        return aggregate, months
