# Ceny zakupu ENEA / PGE (DEV)

W **Taryfy** dodaj brakujące presety operatora. Dostępne są nowe kombinacje:

- ENEA G11 + Ceny Dynamiczne;
- ENEA G12sezON + Ceny Dynamiczne;
- ENEA G13active + Ceny Dynamiczne;
- PGE G11 + Dynamiczna energia, osobno odbiorca i prosument;
- PGE G12e + Dynamiczna energia dla prosumenta, **wyłącznie poza obszarem z odrębnymi godzinami**, z harmonogramem G12w.

To jawne połączenia grup dystrybucji i ofert sprzedaży. G13active i G12sezON
mają miesięczny kalendarz dystrybucji ENEA Operator, bez Kompasu PSE.
Cena energii nie jest ceną dystrybucji. Dotychczasowy TAURON G14dynamic działa
niezależnie i nadal pobiera strefy Kompasu PSE.

W edytorze każdej taryfy pole **Cena energii** pozwala wybrać ceny stałe,
ENEA albo PGE. Przy API ceny energii wpisane w strefach są nieaktywne;
dystrybucja, VAT, akcyza, opłaty i harmonogram pozostają edytowalne. Użytkownik
może zatem połączyć ofertę sprzedaży z własnym dystrybutorem. Synchronizacja
**nigdy nie zmienia definicji taryf**, także własnych, edytowanych i skopiowanych.
Nowa instalacja pozostaje pusta; aktualizacja nie instaluje presetów.

## Źródła i warunki

Zweryfikowano 17.11.2026. Presety obejmują stawki dystrybucji 2026 i wariant
3-fazowy. Godziny przyjmują licznik automatycznie zmieniający czas
Europe/Warsaw. Dla zegara utrzymującego czas zimowy dostosuj godziny letnie.

**ENEA:** [oficjalna strona cen](https://www.enea.pl/ceny-dynamiczne)
korzysta z publicznego endpointu
`https://www.enea.pl/api/enea-prices/individual/DD.MM.RRRR`.
Ceny godzinowe są detaliczne brutto za kWh, zawierają marżę, akcyzę oraz VAT.
Aplikacja dzieli je przez 1,23 i odejmuje 0,005 zł akcyzy, aby dodać dystrybucję
i pozostałe opłaty oraz naliczyć podatki tylko raz. Cena z API może być ujemna;
nie nakładamy nieprzewidzianej umową dolnej granicy.

[Oferta DI12010328_G](https://www.enea.pl/media/10114/cennik-oferty-ceny-dynamicznedi12010328god-01102026-do-31122026pdf.pdf)
z okresu 01.10–31.12.2026 ma marżę 0,0820 zł/kWh netto; jest już w cenach ENEA.
W presetach opłata handlowa e-faktura wynosi 9,99 zł brutto miesięcznie
(9,99 / 1,23 netto). Wariant papierowy to 22,29 zł brutto, deklarowany magazyn
energii 0 zł — użytkownik zmienia opłatę zgodnie z umową.
Nie dodajemy odrębnej oferty Ceny Dynamiczne Max z limitem okresu rozliczeniowego.
Harmonogram i stawki [ENEA Operator, §2.2.10–12](https://www.operator.enea.pl/media/5191/enea-operatorwyciag-z-taryfy01102026-31122026pdf.pdf)
obowiązują również w weekendy i święta, bez dodatkowej całodziennej ulgi.

**PGE:** dane TGE pobieramy z publicznego DataHub PGE
`https://datahub.gkpge.pl/api/tge/quote`.
Filtr dat dotyczy **dnia notowania**, a `quotationDate` wskazuje następny dzień
dostawy. Godziny zweryfikowano z cenami detalicznymi ENEA: etykieta `+00:00`
w odpowiedzi DataHub opisuje zegar rynku, nie godzinę, którą można przesunąć do
Warszawy jak UTC. W bazie zapisujemy dopiero jednoznaczne godziny UTC dostawy.

[Warunki Dynamiczna energia, ed. 1.2026](https://www.gkpge.pl/content/download/6f23e27ebdb19716dc20233047913cc5/file/zal-nr-2-ceny-energii-elektrycznej-dla-g1x.pdf?contentId=143446&inLanguage=pol-PL&version=26)
przewidują Fixing I do końca 2026, Fixing II od 2027. Cena rynkowa jest ograniczona
do 0–4000 zł/MWh, dzielona przez 1000, a następnie powiększana o dodatek netto:
0,0855 zł/kWh dla odbiorcy albo 0,1150 dla prosumenta. Opłaty handlowe netto:
22 zł/mies. i 27 zł/mies. Akcyza oraz VAT są dodawane osobno. Dodatek można
zmienić w edytorze; wybór wariantu umowy należy do użytkownika, nie zmienia się
samoczynnie po przełączeniu trybu prosumenta w analizie.

**G12e:** [taryfa dystrybucyjna PGE, §2.2.8–9](https://pgedystrybucja.pl/content/download/15f0a79cad0e85c168cd6b8430b4a2e9/file/tekst-jednolity-od-01.02.2026_taryfa-pge-dystrybucja-na-rok-2026.pdf?contentId=27274&inLanguage=pol-PL&version=3)
rozróżnia zwykły harmonogram G12w i osobny obszar z godzinami publikowanymi na
[stronie taryfy elastycznej](https://pgedystrybucja.pl/taryfaelastyczna).
Nie udało się zweryfikować tego specjalnego harmonogramu z dostępnego źródła
operatora, dlatego **nie ma automatycznego presetu tego obszaru**. Dodany preset
wyraźnie obejmuje tylko pozostały obszar, a cenę energii bierze z oferty dynamicznej,
nie z niezweryfikowanego Cennika Podstawowego G12e. Przed użyciem sprawdź swoje PPE.

## Historia, aktualizacja i braki

Ceny zakupu mają osobną tabelę SQLite `purchase_prices`, niezależną od RCE/RCEm
sprzedaży prosumenta i Kompasu PSE. Jeden zapis źródło–godzina jest wspólny dla
wszystkich taryf. Pobieranie zaczyna się dopiero po dodaniu taryfy używającej API.
Najpierw pobierane są dziś i jutro, potem historia od najnowszych dni wstecz,
nie wcześniej niż 22.08.2024 (początek publicznego kalendarza ENEA).
Nie oznacza to gwarancji dostępności obu źródeł od tego dnia.

Pełne historyczne doby są pobierane raz. Restart i kolejne analizy korzystają
z bazy; brakujące doby są ponawiane, a dziś i jutro aktualizowane co godzinę.
Błąd starszego archiwum zatrzymuje pobieranie danego źródła wstecz, ale nie usuwa
zapisanych cen. Analiza może niezależnie uzupełnić żądany zakres. Po 20 sekundach
uzupełnianie analizy ustępuje pracy w tle; ponów analizę po zakończeniu importu.
Panel w Taryfach pokazuje liczbę godzin, zakres i czas ostatniego zapisu oraz błąd.
Przycisk **Uzupełnij ceny** budzi synchronizację; nie resetuje archiwum ani taryf.

Oba API zwracają obecnie tylko 24 rekordy także dla jesiennej doby 25-godzinnej.
Nie ma potwierdzonej interpretacji powtórzonej godziny. Doby zmiany czasu (23/25 h)
są odrzucane w całości, bez dopisywania lub kopiowania cen. Analiza obejmująca
zużycie w takiej dobie **nie wyceni danej oferty API**; pozostałe taryfy nadal działają.
Tak samo traktowane są nieopublikowane, niepełne, zdublowane i nieprawidłowe ceny.
Nie stosujemy zastępczych cen RCE ani zgadywanego tygodnia poprzedzającego.

Sensor ceny MQTT korzysta z tego samego przelicznika co analiza. Gdy brakuje ceny,
jest niedostępny, natomiast sensor strefy nadal działa na podstawie harmonogramu.
Sensory diagnostyki Kompasu pozostają diagnostyką Kompasu; stan cen ENEA/PGE
jest widoczny w osobnym panelu. Faktura i wykresy miesięczne obejmują rzeczywisty
iloczyn zużycia i ceny każdej dostępnej godziny, również w net-billingu.

To symulacja z historycznymi notowaniami/cenami detalicznymi i skonfigurowanymi
obecnie opłatami oraz stawkami podatków. Nie odtwarza zmian historycznych umów,
VAT, dystrybucji ani bilansowania kwadransowego. Podział stałych opłat nadal jest
proporcjonalny do liczby dni. Zmiana formatu API lub warunków oferty wymaga
aktualizacji integracji, a nie cichego zastąpienia braków ceną stałą.

Połączenie HTTPS z PGE uzupełnia publiczny certyfikat pośredni Certum, pominięty
obecnie przez serwer. Weryfikacja podpisu, zaufanego korzenia, nazwy hosta i daty
ważności pozostaje włączona.
