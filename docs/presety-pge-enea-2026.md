# Presety PGE i ENEA 2026

Zweryfikowano 17.11.2026. Presety przedstawiają aktualny pakiet stawek na okres
01.10–31.12.2026: energię z taryf na 2026 rok, dystrybucję z jakością od lutego
oraz brak abonamentu dystrybucyjnego od października. Nie odtwarzają historycznych
zmian cenników — skonfigurowane stawki obowiązują w całej analizie.

Presety dodajesz na żądanie przyciskami PGE lub ENEA w zakładce Taryfy. Nowa
instalacja ma pustą listę. Aktualizacja nie dodaje presetów i nie zmienia
zapisanych stawek; ponowny import uzupełnia tylko brakujące definicje.

Każdy preset można edytować albo skopiować: ceny energii i dystrybucji, godziny,
opłaty stałe, zmienne, mocową, akcyzę i VAT. Źródła pozostają informacją o bazowym
presecie i są zachowywane po skopiowaniu lub edycji. W aplikacji znajdziesz je
w **Taryfy → Źródła i założenia presetu**, również w edytorze taryfy.
Porównuj definicje odpowiadające Twojej umowie i obszarowi dystrybucji.

## PGE Obrót + PGE Dystrybucja

Ceny netto w zł/kWh, **energia bez akcyzy**. Składnik sieciowy jest podany bez
jakościowej, OZE i kogeneracyjnej. Stała sieciowa dotyczy **3 faz**, zł/miesiąc.

| Preset | Energia dzienna / nocna | Sieciowa dzienna / nocna | Stała sieciowa |
|---|---:|---:|---:|
| PGE G11 | 0,4982 cała doba | 0,3469 cała doba | 9,98 |
| PGE G12 | 0,5656 / 0,3718 | 0,4014 / 0,0765 | 14,40 |
| PGE G12w | 0,5821 / 0,4235 | 0,4276 / 0,0845 | 14,98 |
| PGE G12n | 0,5511 / 0,3912 | 0,3470 / 0,0347 | 14,40 |

G12: nocna 22–6 oraz 13–15 w październiku–marcu albo 15–17 w kwietniu–wrześniu,
we wszystkie dni. G12w dodaje do nocnej całe soboty, niedziele i święta.
G12n: nocna 1–5 oraz całe niedziele i święta. Zwykła sobota nie jest w całości
nocna; dzienna obejmuje 0–1 oraz 5–24. Północ jest dzielona na poprawne przedziały,
a strefa domyślna pozostaje ostatnia.

Źródła:

- [PGE Obrót — ceny energii 01.01–31.12.2026](https://www.gkpge.pl/content/download/eff267b4dc1a772fdca0ca743e12821a/file/ceny-ze-energie-elektryczna-dla-taryfy-dla-energii-elektrycznej-dla-odbiorcow-z-grup-taryfowych-g-zatwierdzone-przez-prezesa-ure-na-okres-od-1-stycznia-2026-do-31-grudnia-2026.pdf?inLanguage=pol-PL&version=3&contentId=197479): tabela S1/S2; przypis potwierdza brak VAT i akcyzy w cenie netto.
- [PGE Dystrybucja — tekst jednolity od 01.02.2026](https://pgedystrybucja.pl/content/download/15f0a79cad0e85c168cd6b8430b4a2e9/file/tekst-jednolity-od-01.02.2026_taryfa-pge-dystrybucja-na-rok-2026.pdf?contentId=27274&inLanguage=pol-PL&version=3): pkt 2.2.6–2.2.8 (godziny), 2.2.11 (zegar), 7.9 (sieciowe), 7.11–7.13 (OZE, kogeneracja, mocowa).

## ENEA S.A. + ENEA Operator

Te same jednostki i zasady: netto, energia bez akcyzy, stała sieciowa dla 3 faz.

| Preset | Energia dzienna / nocna | Sieciowa dzienna / nocna | Stała sieciowa |
|---|---:|---:|---:|
| ENEA G11 | 0,4980 cała doba | 0,2456 cała doba | 10,41 |
| ENEA G12 | 0,5779 / 0,3369 | 0,2779 / 0,0913 | 14,56 |
| ENEA G12w | 0,6518 / 0,3465 | 0,2702 / 0,0813 | 26,23 |

G12w: szczyt 6–21 w dni robocze, bez tańszego okna popołudniowego. Poza szczytem
21–6 oraz całe soboty, niedziele i święta.

**ENEA G12 jest wariantem do sprawdzenia z własnym licznikiem:** taryfa przewiduje
8 kolejnych godzin z zakresu 22–7 i 2 kolejne z zakresu 13–17; konkretne godziny
ustala operator. Przyjęliśmy 22–6 i 13–15, codziennie. Założenie jest widoczne
w opisie i źródłach presetu. Jeżeli Twoje PPE ma inne godziny, zmień je w edytorze.

Źródła:

- [ENEA — standardowa taryfa sprzedaży od 01.01.2026](https://www.enea.pl/media/6808/taryfa-dla-energii-elektrycznej-dla-odbiorcow-z-grup-taryfowych-g-obowiazuje-od-01012026): pkt 5 (ceny bez VAT i akcyzy), pkt 3.2 (strefy operatora i zegar), dodatkowa tabela cen brutto do kontroli podatków.
- [ENEA Operator — wyciąg 01.10–31.12.2026](https://www.operator.enea.pl/media/5191/enea-operatorwyciag-z-taryfy01102026-31122026pdf.pdf): pkt 2.2.5 i 2.2.7 (godziny), 7.2 (sieciowe), 7.7–7.10 i przypisy (jakość, OZE, kogeneracja, mocowa, abonament).

## Wspólne opłaty i założenia

Jakościowa 0,0332 zł/kWh, OZE 0,0073 zł/kWh, kogeneracyjna 0,0030 zł/kWh.
Mocowa: miesięczne progi netto 4,29 / 10,31 / 17,18 / 24,05 zł według rocznego
poboru, wpisanego przez użytkownika lub oszacowanego z analizy. Akcyza 0,005 zł/kWh,
VAT 23%, dodawane raz. Opłata handlowa i przejściowa 0 zł; abonament dystrybucyjny
0 zł w aktualnym wariancie od 01.10.2026. Nie przenosimy dawnych abonamentów do
opłaty sprzedawcy bez zatwierdzonej stawki z jego taryfy. Dostosuj opłaty do umowy.

Źródła: powyższe taryfy oraz [rozporządzenie taryfowe z 03.09.2026, Dz.U. poz. 1182](https://www.operator.enea.pl/media/4069/rozptaryfowetjdzu20261182od-05092026pdf.pdf),
zwłaszcza § 23 i przepisy przejściowe § 56;
[ENEA — komunikat jakościowy od lutego](https://www.operator.enea.pl/media/3817/uslugi-dystrybucyjne/zmiana-taryfy-w-zakresie-oplaty-jakosciowej-od-1-lutego-2026rpdf).

**Zegar:** presety zakładają automatyczne utrzymanie godzin w czasie
Europe/Warsaw, czyli przełączanie czasu letniego i zimowego. Obie taryfy dopuszczają
również liczniki utrzymujące czas zimowy cały rok. Dla nich należy dostosować
letnie godziny (np. rozdzielić reguły na miesiące). Nie wykrywamy ustawienia
zegara z encji HA. Weekendy i święta są wyznaczane z polskiego kalendarza.

Nie dodano taryf z progami zależnymi od poprzedniego roku (np. G12as),
ofert pakietowych, przedpłatowych ani innych specjalnych produktów. Wymagałyby
odrębnych założeń lub mechanizmów; standardowy preset nie udaje ich obsługi.
