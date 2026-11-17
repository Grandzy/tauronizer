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

# These are explicit pairings of a distribution group and a purchase offer.
# G13active/G12sezON do not inherit G11's regulated energy price.
ENEA_DYNAMIC = 'https://www.enea.pl/media/10114/cennik-oferty-ceny-dynamicznedi12010328god-01102026-do-31122026pdf.pdf'
PGE_DYNAMIC = 'https://www.gkpge.pl/content/download/6f23e27ebdb19716dc20233047913cc5/file/zal-nr-2-ceny-energii-elektrycznej-dla-g1x.pdf?contentId=143446&inLanguage=pol-PL&version=26'


def _dynamic(base_id, id, name, *, prosumer=False):
    preset = copy.deepcopy(next(p for p in SUPPLIER_PRESETS if p['id'] == base_id))
    preset.update(id=id, name=name)
    config = preset['config']
    enea = id.startswith('enea_')
    config.update(energy_source='enea_dynamic' if enea else 'pge_dynamic',
                  energy_markup_net=.115 if prosumer else .0855)
    for zone in config['zones']:
        zone['energy_net'] = 0  # Not used for API offers, never a fallback price.
    next(f for f in config['fixed_fees'] if f['name'] == 'Opłata handlowa')['net_monthly'] = 9.99 / 1.23 if enea else (27 if prosumer else 22)
    preset['description'] = ('Cena energii z API, dystrybucja według godzin grupy. ' +
        ('ENEA Ceny Dynamiczne: wariant e-faktura, opłata 9,99 zł brutto/mies.' if enea else
         f'PGE Dynamiczna energia, wariant {"prosument" if prosumer else "odbiorca bez prosumenta"}.'))
    ref = config['reference']
    ref['sources'][0] = dict(label='Warunki oferty dynamicznej', url=ENEA_DYNAMIC if enea else PGE_DYNAMIC)
    ref['note'] = ('Oferta dynamiczna: historyczne ceny zakupu, aktualne stawki dystrybucji i warunki oferty stosowane do całej analizy. '
        'To symulacja, nie odtworzenie historycznych umów. 3 fazy, godziny Europe/Warsaw przy automatycznej zmianie czasu. ' +
        ('ENEA: ceny brutto publikowane przez sprzedawcę, zawierają marżę, akcyzę i VAT; aplikacja rozdziela je przed dodaniem dystrybucji. '
         'Opłata handlowa e-faktura 9,99 zł brutto; papier 22,29 zł, magazyn energii 0 zł — dostosuj do umowy. '
         'Nie jest to oferta Ceny Dynamiczne Max.' if enea else
         'PGE: TGE Fixing I do końca 2026, Fixing II od 2027; notowanie ograniczone do 0–4000 zł/MWh, '
         f'dodatek {config["energy_markup_net"]:.4f} zł/kWh netto, akcyza i VAT osobno. '
         f'Handlowa {27 if prosumer else 22} zł netto/mies. Warunki ed. 1.2026.'))
    return preset


SUPPLIER_PRESETS.extend([
    _dynamic('enea_g11', 'enea_g11_dynamic', 'ENEA G11 + Ceny Dynamiczne'),
    _dynamic('pge_g11', 'pge_g11_dynamic', 'PGE G11 + Dynamiczna energia'),
    _dynamic('pge_g11', 'pge_g11_dynamic_prosumer', 'PGE G11 + Dynamiczna energia (prosument)', prosumer=True),
])

_season = _dynamic('enea_g12', 'enea_g12sezon_dynamic', 'ENEA G12sezON + Ceny Dynamiczne')
_season['description'] += ' Dwie strefy dystrybucji; miesięczny harmonogram ENEA Operator, bez Kompasu PSE.'
_season['config']['zones'] = [
    _zone('zalecana_zima','Zalecany pobór (zima)',0,.0913,months=[1,2,3,10,11,12],intervals=['00:00-06:00','11:00-13:00','22:00-24:00']),
    _zone('zalecana_lato','Zalecany pobór (lato)',0,.0913,months=[4,5,6,7,8,9],intervals=['04:00-06:00','09:00-17:00']),
    _zone('pozostale','Pozostałe godziny — strefa domyślna',0,.2779,default=True),
]
_active = _dynamic('enea_g12', 'enea_g13active_dynamic', 'ENEA G13active + Ceny Dynamiczne')
_active['description'] += ' Trzy strefy dystrybucji; miesięczny harmonogram ENEA Operator, bez Kompasu PSE.'
_restrictions = [([1],['07:00-10:00','15:00-20:00']),([2],['07:00-09:00','16:00-21:00']),
                 ([3],['06:00-09:00','16:00-23:00']),([4],['06:00-09:00','18:00-23:00']),
                 ([5,6,7,8],['06:00-09:00','18:00-23:00']),([9],['06:00-09:00','17:00-23:00']),
                 ([10],['07:00-09:00','16:00-23:00']),([11],['07:00-09:00','14:00-21:00']),
                 ([12],['07:00-10:00','13:00-20:00'])]
_active['config']['zones'] = [
    *[_zone(f'ograniczanie_{months[0]}','Zalecane ograniczanie',0,.3032,months=months,intervals=intervals) for months,intervals in _restrictions],
    _zone('zalecana_noc','Zalecany pobór',0,.0730,months=[1,2,11,12],intervals=['00:00-06:00','23:00-24:00']),
    _zone('zalecana_dzien','Zalecany pobór',0,.0730,months=[3,4,9,10],intervals=['10:00-16:00']),
    _zone('zalecana_lato','Zalecany pobór',0,.0730,months=[5,6,7,8],intervals=['09:00-17:00']),
    _zone('pozostale','Pozostałe godziny — strefa domyślna',0,.2456,default=True),
]
_g12e = _dynamic('pge_g12w','pge_g12e_dynamic_prosumer', 'PGE G12e + Dynamiczna energia (prosument, godziny G12w)',prosumer=True)
_g12e['description'] = ('Wyłącznie prosument poza obszarem z odrębnym harmonogramem G12e. Godziny jak G12w. '
    'Energia: PGE Dynamiczna energia; to nie Cennik Podstawowy G12e. Sprawdź obszar swojego PPE przed analizą.')
for _zone_row in _g12e['config']['zones']:
    _zone_row['distribution_net'] = .0349 if _zone_row.get('is_default') else .3851
_g12e['config']['fixed_fees'][0]['net_monthly'] = 29.96
_g12e['config']['reference']['note'] += ' G12e: tylko poza obszarem z odrębnymi godzinami z §2.2.9. Obszar elastyczny nie jest obsługiwany automatycznie; sprawdź PPE na stronie operatora i ustaw właściwe godziny.'
_g12e['config']['reference']['sources'].append(dict(label='Obszar i odrębne godziny G12e — sprawdź PPE', url='https://pgedystrybucja.pl/taryfaelastyczna'))
SUPPLIER_PRESETS.extend([_season, _active, _g12e])
