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

## Wymagania dotyczące encji

Sensor musi mieć statystyki długoterminowe w Home Assistant:

- `device_class: energy` albo `state_class: total_increasing`, oraz
- jednostkę energii: Wh, kWh, MWh, GWh, GJ, MJ, kJ lub J.

Tauronizer pobiera **zmiany godzinowe** (`change`), a nie stan licznika.
Jeśli w wybranym zakresie nie ma danych, sprawdź, czy HA zbiera statystyki
dla tej encji (rozwój narzędzi → Statystyki) i czy encja nie została dodana
niedawno.

## Taryfy

- **G11, G12, G12w, G13** to presety przykładowe. Stawki netto są
  orientacyjne — wpisz wartości z aktualnego cennika Tauron i swojej umowy.
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

## Metodologia

- Czas lokalny `Europe/Warsaw`, z uwzględnieniem zmiany czasu, weekendów i
  świąt (w tym ruchomych: Wielkanoc, Zielone Świątki, Boże Ciało).
- Opłaty stałe miesięczne są rozliczane proporcjonalnie do liczby dni.
- Szacunek roczny skaluje koszty zmienne do 365,25 dnia i dodaje 12 opłat
  stałych.
- VAT jest doliczany do sumy netto; akcyza i opłaty zmienne od każdej kWh.
- Ujemne przyrosty (resety licznika) są pomijane z ostrzeżeniem.

To porównanie przy niezmienionym profilu zużycia. Nie jest to prognoza cen
ani oferta handlowa.

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
