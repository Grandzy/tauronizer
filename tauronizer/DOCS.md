# Tauronizer

Porównuje taryfy energii Tauron na podstawie godzinowego zużycia z Home
Assistant. Pokazuje pełny koszt rachunku (energia, dystrybucja, opłaty stałe
i zmienne, akcyza, VAT) oraz najtańszą taryfę dla Twojego profilu zużycia.

## Szybki start

1. Otwórz **Tauronizer** w menu bocznym Home Assistant.
2. W sekcji **Analiza** wybierz encję energii (np. `sensor.energia_dom`).
3. Ustaw zakres dat — np. ostatnie 30 dni, rok albo poprzedni rok.
4. Zostaw wybrane wszystkie taryfy i kliknij **Analizuj zużycie**.

Wynik zawiera najtańszą taryfę, koszt w okresie, szacunek roczny, listę
rankingową, rozbicie kosztów, zużycie według stref, wykres miesięczny i mapę
zużycia dzień tygodnia × godzina. Analiza zapisuje się automatycznie w
**Historii** (maks. 200 pozycji).

## Sensory — aktualna strefa przez MQTT

1. Skonfiguruj broker oraz integrację **MQTT** w Home Assistant. Włącz MQTT Discovery
   ze standardowym prefiksem `homeassistant`.
2. W Tauronizerze otwórz **Ustawienia**, wybierz obecną taryfę spośród zdefiniowanych
   w zakładce **Taryfy** i kliknij **Zapisz i opublikuj**.
3. W Home Assistant w integracji MQTT pojawi się urządzenie **Tauronizer**
   z encją `sensor.tauronizer_strefa`. Zajęty lub ręcznie zmieniony identyfikator
   encji może spowodować zachowanie innej nazwy przez Home Assistant.

Stan encji to dokładna nazwa aktualnej strefy, np. `Szczyt` dla G12 w piątek
od 15:00 do 22:00. Atrybuty zawierają `tariff_id`, `tariff_name` i `zone_id`.
Obowiązuje ten sam silnik co w analizie: czas Europe/Warsaw, godziny, sezony,
weekendy, święta oraz strefa domyślna.

Publikacja działa w tle również przy zamkniętej stronie. Taryfa jest zapamiętywana
w bazie dodatku. Zmiana strefy jest sprawdzana na granicy godzin, a edycja wybranej
taryfy od razu budzi publikację. Stan i discovery są ponawiane co 30 sekund,
również po odzyskaniu połączenia. Po 90 sekundach bez aktualizacji encja staje
się niedostępna; nie steruj urządzeniami na podstawie stanu `unavailable`.

Nie trzeba podawać danych brokera: publikacja przechodzi przez udokumentowaną
akcję `mqtt.publish` w Home Assistant, z istniejącymi uprawnieniami dodatku.
Discovery ma temat `homeassistant/sensor/tauronizer/strefa/config`, a stan
`tauronizer/strefa/state`. Tylko konfiguracja discovery jest zachowywana przez
broker (retain); stara strefa nie jest odtwarzana po restarcie.

Opcja **Nie publikuj sensorów** wyłącza publikację i usuwa konfigurację discovery.
Usunięcie wybranej taryfy także wycofuje encję, dopóki nie wybierzesz innej taryfy.
Błąd MQTT nie kasuje wyboru — status w zakładce pokaże problem, a dodatek ponowi próbę.
Własne zmiany nazw stref od razu wpływają na stan encji, dlatego uwzględnij je
w automatyzacjach.

### Sensor aktualnej ceny kWh

`sensor.tauronizer_cena_kwh` publikuje liczbę w jednostce `PLN/kWh`, dla tej samej
obecnej taryfy i strefy co `sensor.tauronizer_strefa`. W zakładce **Ustawienia** wybierz
**Brutto — z VAT** (domyślnie) lub **Netto — bez VAT**, a następnie zapisz ustawienia.
Wybór jest zapamiętywany po restarcie.

Cena netto = energia netto + dystrybucja netto + suma wszystkich opłat zmiennych
z taryfy + akcyza. Cena brutto = cena netto × (1 + VAT/100), według VAT wybranej taryfy.
Obejmuje również własne opłaty zmienne dodane do taryfy; nie obejmuje opłat
miesięcznych ani miesięcznej opłaty mocowej.

Cena jest publikowana z dokładnością do 6 miejsc po przecinku, z sugerowanym
wyświetlaniem 4 miejsc w Home Assistant. Atrybut `price_mode` ma wartość `net` lub
`gross`, a dodatkowe atrybuty zawierają taryfę, strefę i składniki ceny netto.
Temat discovery: `homeassistant/sensor/tauronizer/cena_kwh/config`;
temat stanu: `tauronizer/cena_kwh/state`.

Oba sensory aktualizują się razem po zmianie taryfy, strefy lub trybu ceny i mają
ten sam mechanizm niedostępności po 90 sekundach bez aktualizacji. Wyłączenie
publikacji albo usunięcie obecnej taryfy usuwa discovery obu sensorów.

## G14dynamic i lokalna historia Kompasu PSE

Preset **Tauron G14dynamic** korzysta z czterech stref przypisywanych do godzin
przez **Energetyczny kompas PSE**. To zmienna dystrybucja, a nie giełdowa cena energii:
energia pozostaje stała według cennika „Prąd ze zmienną dystrybucją”.

| Strefa | Dystrybucja netto, zł/kWh |
|---|---:|
| S1 — Zalecane użytkowanie | 0,0224 |
| S2 — Normalne użytkowanie | 0,0893 |
| S3 — Zalecane oszczędzanie | 0,3881 |
| S4 — Wymagane ograniczenie | 2,3756 |

Preset 2026 przyjmuje energię **0,4970 zł/kWh netto bez akcyzy** + 0,0050 zł/kWh
akcyzy, czyli 0,5020 zł/kWh netto z akcyzą z cennika TAURONA. OZE, kogeneracja,
jakościowa, VAT i miesięczna mocowa są doliczane jak w innych taryfach. Domyślnie
3 fazy; abonament pominięto zgodnie z zaprzestaniem naliczania od 1.10.2026.
Stawki i nazwy można edytować; godzin S1–S4 nie ustawia się ręcznie.

Źródła: [cennik TAURON G14dynamic od 1.01.2026](https://www.tauron.pl/-/media/offer-documents/produkty/g14dynamic/ts/cennik/ee-gd-bsc-b-dynd-ts-0.ashx),
[taryfa dystrybucyjna TAURON 2026](https://www.tauron-dystrybucja.pl/-/media/offer-documents/dystrybucja/aktualna-taryfa/taryfa-tauron-dystrybucja-2026_ocr.ashx),
[mapowanie pól PSE](https://api.raporty.pse.pl/EndpointsMap.pdf).

### Import i aktualizacje

- Po uruchomieniu dodatek zapisuje w SQLite wszystkie dostępne aktywne wskazania
  `https://api.raporty.pse.pl/api/pdgsz`. Zweryfikowany początek historii: **14.06.2024**.
- Najpierw pobiera ostatnie dni, następnie importuje historię stronami w tle.
  Każda strona i punkt wznowienia są zapisywane razem w transakcji. Restart nie
  powoduje ponownego importu ukończonej części.
- Co 15 minut uzupełnia ostatnie dni i dzień następny, jeśli PSE go już opublikowało,
  oraz nowe dni archiwum. Nie pobiera ponownie całej historii.
- Luki są wykrywane z uwzględnieniem dni mających 23 i 25 godzin. Brakujące dni
  są ponawiane w ograniczonych, rotujących partiach. Po błędzie API dane zostają
  w bazie, a synchronizacja jest ponawiana po minucie.
- Sekcja w zakładce **Taryfy** pokazuje postęp, zakres, liczbę godzin, braki i datę
  synchronizacji; przycisk **Uzupełnij dane** budzi synchronizację w tle.
- Analizy i sensory MQTT używają lokalnych danych. Przy braku strefy dla potrzebnej
  godziny G14dynamic pokazuje błąd, zamiast przyjmować najtańszą strefę. Pozostałe
  taryfy nadal są porównywane. Sensor czeka na dane i wygasa przy braku aktualizacji.
- Klucze godzin zapisujemy w UTC, dzięki czemu obie jesienne godziny 02:00 są
  rozróżniane. W G14dynamic weekend lub święto nie zastępuje wskazania Kompasu.

Porównanie jest symulacją obecnego cennika dla historycznego zużycia: **nie
odtwarza zmian cenników TAURONA z poprzednich lat**. Wskazania Kompasu to najnowsza
aktywna rewizja PSE, a nie komplet kolejnych wersji prognoz. Dane sprzed początku
publicznego archiwum nie są wymyślane ani ekstrapolowane.

**G12n:** nie jest grupą w aktualnej taryfie TAURON Dystrybucja. Występuje m.in.
u PGE, dlatego nie dodano jej do presetów TAURONA. Nie jest zamiennikiem G12w.

## Wymagania dotyczące encji

Sensor musi mieć statystyki długoterminowe w Home Assistant:

- `device_class: energy` albo `state_class: total_increasing`, oraz
- jednostkę energii: Wh, kWh, MWh, GWh, GJ, MJ, kJ lub J.

Tauronizer pobiera **zmiany godzinowe** (`change`), a nie stan licznika.
Jeśli w wybranym zakresie nie ma danych, sprawdź, czy HA zbiera statystyki
dla tej encji (rozwój narzędzi → Statystyki) i czy encja nie została dodana
niedawno.

## Taryfy

Nowa instalacja nie zawiera żadnych taryf. Przyciski **Dodaj presety TAURON**,
**Dodaj presety PGE**, **Dodaj presety ENEA** dodają tylko brakujące definicje
wybranego operatora. Możesz też wybrać **Nowa taryfa**. Ponowne dodanie presetów
nie tworzy duplikatów i nie zmienia zapisanych taryf.

Aktualizacje i restarty zachowują wszystkie istniejące taryfy: własne, kopie,
zmienione presety i same zmiany nazw lub opisów. Nie dopisują nowych presetów,
nie odtwarzają usuniętych i nie odświeżają automatycznie cen.

- **G11, G12, G12w, G13**: ceny TAURON Sprzedaż 2026 (bez obszaru gliwickiego
  i ofert rynkowych), dystrybucja ze stawką jakościową od 01.02.2026.
  Ceny netto, energia bez akcyzy. Domyślnie 3 fazy i abonament 0 zł (od 1.10.2026);
  wartości i źródła opisuje [README](https://github.com/direk/tauronizer#stawki-tauron-2026).
- **Edytuj** zmienia wybraną taryfę lokalnie; aktualizacje nie nadpisują zmian.
  Aby wczytać bazowy preset ponownie, usuń tę definicję i dodaj presety jej
  operatora. Zduplikuj ją wcześniej, jeśli chcesz zachować poprzedni wariant.
- **Duplikuj** tworzy własną kopię, której aktualizacje dodatku nie zmieniają.
- **Nowa taryfa** pozwala zdefiniować dowolne strefy.

### Jak działa strefa

Strefa pasuje, gdy zgadzają się wszystkie warunki:

1. **miesiące** — opcjonalne; brak zaznaczeń oznacza cały rok,
2. **dni tygodnia**,
3. **godziny** — pełne godziny, np. `06:00-13:00, 15:00-22:00`; cała doba to
   `00:00-24:00`,
4. **święta** — opcja „Święta traktuj jak pozaszczyt” wyłącza strefę w
   polskie dni ustawowo wolne.

Kolejność stref ma znaczenie: **pierwsza pasująca wygrywa**. Ostatnia strefa
powinna obejmować całą dobę. Aplikacja nie pozwoli zapisać taryfy, która nie
pokrywa całego roku, wszystkich dni i godzin (także w święta).

Przykład sezonowy (G13, szczyt popołudniowy): dni robocze, godziny
`16:00-21:00`, miesiące X–III; druga strefa `19:00-22:00` dla IV–IX.

### Opłata mocowa i opłaty miesięczne

Opłata mocowa ma osobną sekcję w edytorze taryfy. Jest miesięcznym ryczałtem
netto: poniżej 500 kWh — 4,29 zł; 500–1200 — 10,31 zł;
powyżej 1200 do 2800 — 17,18 zł; powyżej 2800 — 24,05 zł.
Wpisz pobór z sieci, według którego Tauron kwalifikuje odbiorcę na ostatnim
odczycie (zwykle ostatnie 12 miesięcy; dla nowego odbiorcy dotychczasowy pobór,
przed pierwszym odczytem 0). Puste pole szacuje roczny pobór z okresu analizy.
Nie wpisuj tej opłaty drugi raz w opłatach stałych lub zmiennych.
Wynik pokazuje podstawę progu i stawkę, również gdy jest to szacunek.

W opłatach stałych zmień sieciową na 7,38 zł dla 1 fazy lub 10,86 zł dla 3 faz.
Abonament od 1.10.2026 nie jest naliczany: 0 zł. Historyczne stawki dla cyklu 1/2/6/12 miesięcy wynosiły 4,56/2,28/0,76/0,38 zł netto.
Opłatę handlową wpisz z umowy (w taryfie sprzedawcy 0 zł).

Aktualizacja zachowuje wszystkie zapisane taryfy bez zmian; stawki popraw
ręcznie. Przyciski operatorów dodają tylko brakujące presety. Zapisane wyniki nie są przeliczane.

## Metodologia

- Czas lokalny `Europe/Warsaw`, z uwzględnieniem zmiany czasu, weekendów i
  świąt (w tym ruchomych: Wielkanoc, Zielone Świątki, Boże Ciało).
- Opłaty stałe miesięczne są rozliczane proporcjonalnie do liczby dni.
- Szacunek roczny skaluje koszty zmienne do 365,25 dnia i dodaje 12 opłat
  stałych i mocowych.
- VAT jest doliczany do sumy netto; akcyza i opłaty zmienne od każdej kWh.
- Ujemne przyrosty (resety licznika) są pomijane z ostrzeżeniem.

To porównanie przy niezmienionym profilu zużycia. Nie jest to prognoza cen
ani oferta handlowa. Jeden cennik i jeden próg mocowej obowiązują w całym
zakresie; dodatek nie odtwarza historycznych zmian cen ani kwalifikacji Taurona.
Stawki ze stycznia 2026 (jakościowa 0,0331) wymagają własnej taryfy.
Pełne miesiące i abonament na fakturze mogą być rozliczane inaczej niż
proporcjonalny szacunek dodatku.

## Dane i prywatność

Taryfy, ustawienia i historia analiz są zapisane w `/data/tauronizer.db`
(SQLite). Dodatek nie wysyła danych poza Home Assistant. Usunięcie dodatku
usuwa jego dane.

Dostęp do panelu wynika z uprawnień Home Assistant i Ingress. Każdy
użytkownik widzący panel może przeglądać historię i edytować taryfy. Aby
ograniczyć panel do administratorów, ustaw `panel_admin: true` w
`config.yaml` i przebuduj dodatek.

## Rozwiązywanie problemów

- **„Brak statystyk długoterminowych”** — encja nie ma `state_class`
  `total_increasing`/`total`, nie jest energią lub HA dopiero zaczął zbierać
  dane. Sprawdź narzędzia deweloperskie → Statystyki.
- **Statystyki zaczynają się później** — aplikacja pokaże ostrzeżenie i
  policzy to, co jest dostępne.
- **Dziwny wynik** — sprawdź jednostkę encji i stawki w edytorze taryfy.
  Pamiętaj, że preset G12 traktuje święta jak dzień roboczy, a G12w/G13 jak
  pozaszczyt.
- **Brak panelu w menu** — uruchom dodatek i odśwież stronę Home Assistant;
  sprawdź log dodatku.

## Miesięczny profil i porównanie kosztów

Pod profilem godzinowym znajduje się heatmapa sum zużycia dla każdej pary
miesiąc–dzień tygodnia. Miesiące z różnych lat mają osobne wiersze. Pole „—”
oznacza brak statystyk dla danej kombinacji, a 0 kWh oznacza dostępny odczyt zerowy.

Pod zużyciem miesięcznym wykres kosztów pokazuje po dwa słupki na miesiąc:
obecną taryfę zapisaną w **Ustawieniach** oraz najtańszą w całym analizowanym
okresie spośród taryf wybranych do analizy. Jest to zwycięzca głównego rankingu
i ta sama taryfa jest pokazywana we wszystkich miesiącach. Obie nazwy znajdują
się w legendzie; pod słupkami są wyłącznie miesiące. Obecna taryfa jest uwzględniana nawet po odznaczeniu jej
na liście porównania; nie zmienia to głównego rankingu zaznaczonych taryf.

Kwoty obejmują cały rachunek brutto. Opłaty stałe są proporcjonalne do liczby
dni objętych zakresem w miesiącu. Próg mocowej jest wspólny z całą analizą,
więc nie zmienia się wskutek sezonowych wahań zużycia między miesiącami.
Zaokrąglenia mogą dać groszowe różnice względem sumy za cały okres.

Bez wybranej obecnej taryfy aplikacja prosi o ustawienie jej w Ustawieniach.
Proponowana taryfa musi mieć dane dla całej analizy. Braki danych obecnej taryfy
są oznaczane w odpowiednich miesiącach; przyczyny można rozwinąć pod wykresem. Miesiąc bez statystyk zużycia nie ma
wyliczonego kosztu. Nowe wyniki zapisują wykresy i wybraną taryfę w historii.
Starsze analizy wymagają ponownego wykonania, żeby otrzymać nowe wykresy.


## Diagnostyka API taryfy dynamicznej

G14dynamic pobiera strefy z API **Kompasu PSE**, a nie z API TAURONA.
Dodatek automatycznie publikuje przez MQTT Discovery dwie encje diagnostyczne:

- `sensor.tauronizer_api_ostatnia_aktualizacja` — data i godzina ostatniego
  poprawnego pobrania oraz zapisu niepustej strony danych do lokalnej bazy.
  Obejmuje także import historii i ponowne pobranie tych samych danych.
  To czas pobrania, nie data obowiązywania ani publikacji stref przez PSE.
  Pusta odpowiedź i błąd nie zmieniają tej wartości. Data jest zapisywana
  atomowo z danymi, zachowana po restarcie i prezentowana przez HA w lokalnym czasie.
- `binary_sensor.tauronizer_api_polaczenie` — wynik ostatniego zapytania:
  true po poprawnej odpowiedzi o oczekiwanej strukturze (również pustej),
  false po błędzie HTTP, sieci lub nieprawidłowej odpowiedzi. Po 30 minutach
  bez sprawdzenia przyjmuje false. Przed pierwszym sprawdzeniem po restarcie
  pozostaje niedostępny. W HA odpowiada to stanom `on`/`off` i klasie connectivity.

Sprawdzanie odbywa się podczas synchronizacji: zwykle co 15 minut, po błędzie
co minutę, a podczas importu po każdej odpowiedzi. Nie jest to ciągły test sieci
ani potwierdzenie kompletności archiwum. Błędy MQTT są raportowane oddzielnie;
nie zmieniają wyniku sprawdzenia API.

Diagnostyka działa również przy wyłączonej publikacji strefy i ceny lub braku
aktualnych danych G14dynamic. Korzysta z tego samego urządzenia Tauronizer,
ale ma osobne tematy dostępności. Publikacja jest ponawiana co 30 sekund,
bez zatrzymywania ostatniego stanu przez broker; konfiguracja Discovery jest
zatrzymywana. Po 90 sekundach bez publikacji obie encje stają się niedostępne,
a przy poprawnym zamknięciu dodatku są od razu oznaczane jako niedostępne.
Stan i czas ostatniego sprawdzenia można odczytać także w zakładce Ustawienia.


## Kompletność danych zużycia

Analiza pokazuje procent zakończonych godzin z poprawnymi statystykami, podział
na miesiące oraz brakujące przedziały. Przedziały mają wyłączoną godzinę końcową.
Miesiące niepełne z powodu wybranego zakresu są oznaczone jako fragment miesiąca;
kompletność dotyczy tylko dni objętych analizą. Braki mają także oznaczenia ⚠
przy miesiącach na wykresach. Raport jest zapisywany wraz z analizą w Historii.

Godziny są liczone w UTC, a prezentowane w Europe/Warsaw, więc dni zmiany czasu
mają odpowiednio 23 lub 25 godzin. Zerowe zużycie jest poprawnym odczytem.
Trwająca godzina i późniejsze godziny dzisiejszego dnia nie są brakami.
Pominięte ujemne, niefinitywne lub niegodzinowe odczyty nie potwierdzają kompletności.
Powtórzone godziny liczą się raz; do kosztów API używa ostatniego poprawnego odczytu.
Raport sprawdza obecność godzinowych statystyk, nie dokładność samego licznika.

Brakujące zużycie nie jest szacowane. Może zaniżyć koszty i zmienić ranking taryf,
a estymacja roczna i próg mocowej również mogą być mniej miarodajne. Opłaty stałe
nadal dotyczą całego wybranego zakresu. Dla dużej liczby luk wyświetlane jest
pierwsze 200 przedziałów, a podsumowania obejmują wszystkie braki.
Starsze zapisane analizy wymagają ponownego wykonania, aby zawierały ten raport.

## Harmonogram G14dynamic i następna zmiana strefy

W Ustawieniach znajduje się harmonogram opublikowanych stref na dziś i jutro,
odczytywany wyłącznie z lokalnej bazy Kompasu PSE. Kolejne godziny tej samej strefy
są łączone w przedziały. Widać nazwy stref, pełne ceny zmienne brutto (jak sensor
ceny za kWh, bez opłat miesięcznych) i braki danych. Zmiana czasu jest uwzględniona,
a oznaczenia CET/CEST rozróżniają powtarzające się godziny.

Podgląd korzysta z wybranej obecnej taryfy G14dynamic; jeśli obecna taryfa jest
inna, pokazuje pierwszą dostępną definicję G14dynamic jako podgląd.
Brak jutra może oznaczać brak publikacji lub nieukończony import. API PSE może
korygować dane; harmonogram i sensor są odświeżane po aktualizacji lokalnej bazy.

`sensor.tauronizer_nastepna_zmiana_strefy` działa dla obecnej taryfy G14dynamic
wybranej w Ustawieniach. Ma klasę timestamp i stan będący czasem następnej zmiany
poziomu S1–S4 w opublikowanym harmonogramie dziś/jutro. Atrybuty: `tariff_id`,
`tariff_name`, `next_zone`, `next_zone_id`, `next_level` (0–3) i `next_price_gross`.
Jest publikowany przez MQTT Discovery na urządzeniu Tauronizer, niezależnie od
trybu netto/brutto sensora ceny (atrybut ceny przyszłej jest zawsze brutto).

Do potwierdzenia następnej zmiany wymagane są ciągłe dane od aktualnej godziny
po granicę zmiany. Brak aktualnej godziny, luka przed zmianą, brak opublikowanej
kolejnej zmiany lub wybranie innej taryfy oznacza niedostępny sensor, a nie
wymyśloną datę. Stan nie jest zatrzymywany przez broker. Publikacja jest ponawiana
co 30 sekund, na granicach godzin i po aktualizacji danych. Encja ma osobny temat
dostępności i staje się niedostępna po 90 sekundach bez publikacji.


## Wykres struktury faktury

Po rozwinięciu taryfy w **Analiza → Szczegóły rachunku** widoczny jest wykres
pączkowy. Środek przedstawia sumę brutto, a legenda kwoty i udziały poszczególnych
składników: energii, dystrybucji, każdej opłaty zmiennej i stałej z konfiguracji,
akcyzy, opłaty mocowej oraz VAT. Podsumowanie netto i razem brutto nie są osobnymi
wycinkami, dzięki czemu kwoty nie są liczone podwójnie. Najechanie na wycinek
pokazuje nazwę, kwotę i udział; wszystkie wartości są także w legendzie.

Opłaty zerowe są widoczne w legendzie, ale nie tworzą wycinków. Przy zerowej
fakturze pozostaje pusty pierścień i informacja o braku kosztów. Kwoty w legendzie
są zaokrąglane do groszy; udziały wynikają z sumy pozycji przed zaokrągleniem
wyświetlanych kwot, więc możliwe są groszowe różnice względem sumy brutto.
Wykres korzysta z tych samych danych i założeń co reszta analizy.

Nowe wyniki zapisują osobne pozycje faktury w Historii. Starsze wyniki także
pokazują wykres, ale z opłatami zmiennymi i stałymi w grupach; ponowne wykonanie
analizy pozwala zobaczyć szczegółowe pozycje bez zgadywania dawnych stawek.


## Presety PGE i ENEA

Dostępne są PGE G11, G12, G12w, G12n oraz ENEA G11, G12, G12w. Każdy można
edytować i duplikować. W **Taryfy → Źródła i założenia presetu** sprawdzisz
sprzedawcę, dystrybutora, daty, dokumenty oraz przyjęty zegar i godziny.
Wariant domyślny: 3 fazy, aktualne stawki na 01.10–31.12.2026. ENEA G12 ma
przykładową nocną 22–6 i 13–15; dokładne godziny ustala operator — dostosuj je
do swojego PPE. PGE G12/G12w mają sezonową strefę popołudniową, G12n nocną 1–5
oraz całe niedziele i święta. ENEA G12w ma szczyt 6–21 w dni robocze.
Presety zakładają automatyczną zmianę czasu licznika; dla stałego czasu zimowego
dostosuj letnie reguły. Porównuj taryfy odpowiadające swojej umowie i obszarowi.
