"""PGE and ENEA standard household tariffs, verified against official 2026 documents.

Rates exclude VAT and excise. See docs/presety-pge-enea-2026.md for source
sections, dates, meter-clock assumptions and variants intentionally omitted.
"""
from __future__ import annotations

import copy

PGE_ENERGY = 'https://www.gkpge.pl/content/download/eff267b4dc1a772fdca0ca743e12821a/file/ceny-ze-energie-elektryczna-dla-taryfy-dla-energii-elektrycznej-dla-odbiorcow-z-grup-taryfowych-g-zatwierdzone-przez-prezesa-ure-na-okres-od-1-stycznia-2026-do-31-grudnia-2026.pdf?inLanguage=pol-PL&version=3&contentId=197479'
PGE_DISTRIBUTION = 'https://pgedystrybucja.pl/content/download/15f0a79cad0e85c168cd6b8430b4a2e9/file/tekst-jednolity-od-01.02.2026_taryfa-pge-dystrybucja-na-rok-2026.pdf?contentId=27274&inLanguage=pol-PL&version=3'
ENEA_ENERGY = 'https://www.enea.pl/media/6808/taryfa-dla-energii-elektrycznej-dla-odbiorcow-z-grup-taryfowych-g-obowiazuje-od-01012026'
ENEA_DISTRIBUTION = 'https://www.operator.enea.pl/media/5191/enea-operatorwyciag-z-taryfy01102026-31122026pdf.pdf'
SUBSCRIPTION_RULE = 'https://www.operator.enea.pl/media/4069/rozptaryfowetjdzu20261182od-05092026pdf.pdf'


def _zone(id, name, energy, distribution, *, days=range(7), intervals=('00:00-24:00',), months=None, holidays=False, default=False):
    return dict(id=id, name=name, energy_net=energy, distribution_net=distribution,
                days=list(days), intervals=list(intervals), months=months,
                exclude_holidays=holidays, is_default=default)


def _preset(supplier, group, energy, distribution, fixed, description, note, *, peak_zones=None):
    if group == 'g11':
        zones = [_zone('cala_doba', 'Cała doba', energy[0], distribution[0], default=True)]
    else:
        zones = copy.deepcopy(peak_zones)
        for zone in zones:
            zone.update(energy_net=energy[0], distribution_net=distribution[0])
        zones.append(_zone('pozaszczyt', 'Pozostałe godziny — strefa domyślna', energy[1], distribution[1], default=True))
    pge = supplier == 'PGE'
    return dict(id=f'{supplier.lower()}_{group}', name=f'{supplier} {dict(g11="G11", g12="G12", g12w="G12w", g12n="G12n")[group]}',
        description=description,
        config=dict(zones=zones, zone_source='schedule',
            fixed_fees=[dict(name='Opłata stała sieciowa (3 fazy)', net_monthly=fixed),
                        dict(name='Opłata abonamentowa (nienaliczana od 01.10.2026)', net_monthly=0),
                        dict(name='Opłata handlowa', net_monthly=0),
                        dict(name='Opłata przejściowa (2026: 0 zł)', net_monthly=0)],
            variable_fees=[dict(name='Opłata jakościowa',net_per_kwh=.0332),
                           dict(name='Opłata OZE',net_per_kwh=.0073),
                           dict(name='Opłata kogeneracyjna',net_per_kwh=.003)],
            capacity_fee=dict(annual_kwh=None,net_monthly_rates=[4.29,10.31,17.18,24.05]),
            excise_net_per_kwh=.005, vat_percent=23,
            reference=dict(supplier='PGE Obrót' if pge else 'ENEA S.A.',
                distributor='PGE Dystrybucja' if pge else 'ENEA Operator',
                valid_from='2026-10-01',valid_until='2026-12-31',checked_on='2026-11-17',
                note=note + ' Ceny energii z taryfy 2026 bez ofert rynkowych; jakość od 01.02.2026. '
                    'Wariant 3-fazowy, abonament dystrybucyjny 0 zł od 01.10.2026, handlowa 0 zł. '
                    'Godziny w czasie Europe/Warsaw, przy automatycznej zmianie czasu licznika. '
                    'Dla licznika utrzymującego czas zimowy dostosuj letnie godziny. '
                    'Stawki stosowane do całej analizy; nie odtwarzają faktur historycznych.',
                sources=[dict(label='Sprzedaż energii — taryfa 2026',url=PGE_ENERGY if pge else ENEA_ENERGY),
                         dict(label='Dystrybucja — stawki i godziny stref',url=PGE_DISTRIBUTION if pge else ENEA_DISTRIBUTION),
                         dict(label='Rozporządzenie taryfowe — zasady abonamentu',url=SUBSCRIPTION_RULE)])))


def _pge_seasonal(weekend):
    days = range(5) if weekend else range(7)
    return [_zone('szczyt_zima','Dzienna (zima)',0,0,days=days,months=[1,2,3,10,11,12],
                  intervals=['06:00-13:00','15:00-22:00'],holidays=weekend),
            _zone('szczyt_lato','Dzienna (lato)',0,0,days=days,months=[4,5,6,7,8,9],
                  intervals=['06:00-15:00','17:00-22:00'],holidays=weekend)]


SUPPLIER_PRESETS = [
    _preset('PGE','g11',[.4982],[.3469],9.98,
            'PGE Obrót + PGE Dystrybucja, taryfa standardowa 2026. Jedna strefa przez całą dobę. Wariant 3-fazowy; opłaty i ceny można edytować.',
            'Taryfa jednostrefowa.'),
    _preset('PGE','g12',[.5656,.3718],[.4014,.0765],14.40,
            'PGE Obrót + PGE Dystrybucja 2026, 3 fazy. Nocna 22–6 oraz zimą 13–15, latem 15–17, we wszystkie dni. Godziny dla licznika automatycznie zmieniającego czas.',
            'Zima: październik–marzec; lato: kwiecień–wrzesień. Weekendy i święta bez dodatkowego rozszerzenia nocnej.',peak_zones=_pge_seasonal(False)),
    _preset('PGE','g12w',[.5821,.4235],[.4276,.0845],14.98,
            'PGE Obrót + PGE Dystrybucja 2026, 3 fazy. Tańsza strefa: 22–6, zimą 13–15, latem 15–17 oraz całe weekendy i święta. Licznik z automatyczną zmianą czasu.',
            'Zima: październik–marzec; lato: kwiecień–wrzesień.',peak_zones=_pge_seasonal(True)),
    _preset('PGE','g12n',[.5511,.3912],[.3470,.0347],14.40,
            'PGE Obrót + PGE Dystrybucja 2026, 3 fazy. Nocna 1–5 oraz całe niedziele i święta. Zwykła sobota ma dzienną 0–1 i 5–24. Licznik z automatyczną zmianą czasu.',
            'Taryfa niedzielna: sobota nie jest automatycznie cała w strefie nocnej.',
            peak_zones=[_zone('szczyt','Dzienna',0,0,days=range(6),intervals=['00:00-01:00','05:00-24:00'],holidays=True)]),
    _preset('ENEA','g11',[.4980],[.2456],10.41,
            'ENEA S.A. + ENEA Operator, taryfa standardowa 2026. Jedna strefa przez całą dobę. Wariant 3-fazowy; opłaty i ceny można edytować.',
            'Taryfa jednostrefowa.'),
    _preset('ENEA','g12',[.5779,.3369],[.2779,.0913],14.56,
            'ENEA S.A. + ENEA Operator 2026, 3 fazy. Przyjęta nocna 22–6 i 13–15, codziennie. Konkretne 8 godzin z 22–7 i 2 godziny z 13–17 ustala operator — sprawdź swój licznik.',
            'Wariant przykładowy: nocna 22–6 i 13–15. Operator ustala dokładne godziny; dostosuj je do swojego PPE. Weekendy i święta bez dodatkowej tańszej strefy.',
            peak_zones=[_zone('szczyt','Dzienna',0,0,intervals=['06:00-13:00','15:00-22:00'])]),
    _preset('ENEA','g12w',[.6518,.3465],[.2702,.0813],26.23,
            'ENEA S.A. + ENEA Operator 2026, 3 fazy. Szczyt 6–21 w dni robocze, poza szczytem 21–6 oraz całe soboty, niedziele i święta. Licznik z automatyczną zmianą czasu.',
            'Szczyt 6–21, bez dodatkowego tańszego okna popołudniowego w dni robocze.',
            peak_zones=[_zone('szczyt','Szczyt',0,0,days=range(5),intervals=['06:00-21:00'],holidays=True)]),
]
