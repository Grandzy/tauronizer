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
2. W Tauronizerze otwórz **Sensory**, wybierz obecną taryfę spośród zdefiniowanych
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
obecnej taryfy i strefy co `sensor.tauronizer_strefa`. W zakładce **Sensory** wybierz
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

- **G11, G12, G12w, G13**: ceny TAURON Sprzedaż 2026 (bez obszaru gliwickiego
  i ofert rynkowych), dystrybucja ze stawką jakościową od 01.02.2026.
  Ceny netto, energia bez akcyzy. Domyślnie 3 fazy i abonament 0 zł (od 1.10.2026);
  wartości i źródła opisuje [README](https://github.com/direk/tauronizer#stawki-tauron-2026).
- **Edytuj** zmienia wybraną taryfę lokalnie. Zmiany presetów można cofnąć
  przyciskiem **Przywróć presety**.
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

Aktualizacja zachowuje edytowane presety i własne taryfy; ich stawki popraw
ręcznie lub użyj „Przywróć presety”. Zapisane wyniki nie są przeliczane.

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
