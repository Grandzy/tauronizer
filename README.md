# Tauronizer

[![Otwórz Home Assistant i dodaj repozytorium dodatków z Tauronizerem](https://my.home-assistant.io/badges/supervisor_add_addon_repository.svg)](https://my.home-assistant.io/redirect/supervisor_add_addon_repository/?repository_url=https%3A%2F%2Fgithub.com%2Fdirek%2Ftauronizer)

**Porównywarka taryf energii elektrycznej Tauron dla Home Assistant.**

Tauronizer pobiera godzinowe zużycie energii ze statystyk długoterminowych
Home Assistant, przypisuje każdą godzinę do strefy wybranej taryfy i liczy
pełny rachunek: energię czynną, dystrybucję, opłaty stałe i zmienne, akcyzę
oraz VAT. Na tej podstawie pokazuje, która taryfa jest najtańsza dla Twojego
profilu zużycia — w wybranym okresie i w przeliczeniu na rok.

> **Ważne:** wbudowane stawki są wartościami przykładowymi (netto) i służą
> porównaniu taryf. Przed zmianą taryfy zweryfikuj ceny z aktualnym cennikiem
> Tauron i swoją umową. Wszystkie stawki możesz edytować w aplikacji.

## Funkcje

- **Gotowe presety Tauron:** G11, G12, G12w, G13 (z sezonowym szczytem
  popołudniowym w G13). Presety są edytowalne i można je przywrócić.
- **Własne taryfy:** dowolna liczba stref, dni tygodnia, przedziałów
  godzinowych i opcjonalnych ograniczeń miesięcznych (np. tylko zima).
- **Pełny rachunek:** energia, dystrybucja, opłaty stałe miesięczne, opłaty
  zmienne za kWh, akcyza i VAT.
- **Analiza historyczna:** wybór encji energii i zakresu dat (maks. 10 lat),
  porównanie kosztów, oszczędność względem najdroższej taryfy, szacunek roczny.
- **Szczegóły:** rozbicie kosztów, zużycie według stref, wykres miesięczny,
  mapa cieplna zużycia (dzień tygodnia × godzina).
- **Historia analiz:** do 200 zapisanych wyników w bazie dodatku.
- **Bez zewnętrznych zależności frontendu** — działa w panelu Home Assistant
  przez Ingress, także na telefonie. Motyw jasny i ciemny.

## Instalacja jako dodatek Home Assistant

Najszybciej: kliknij przycisk na górze README (albo poniżej) i zatwierdź
dodanie repozytorium w Home Assistant. Przycisk otwiera właściwe okno z
adresem repozytorium już wpisanym.

[![Dodaj repozytorium do Home Assistant](https://my.home-assistant.io/badges/supervisor_add_addon_repository.svg)](https://my.home-assistant.io/redirect/supervisor_add_addon_repository/?repository_url=https%3A%2F%2Fgithub.com%2Fdirek%2Ftauronizer)

Kroki ręczne:

1. W Home Assistant otwórz **Ustawienia → Dodatki → Sklep z dodatkami**.
2. Kliknij menu **⋮ → Repozytoria**, wklej
   `https://github.com/direk/tauronizer` i dodaj.
3. Odśwież sklep, znajdź **Tauronizer** i kliknij **Zainstaluj**.
4. Po instalacji uruchom dodatek. Panel **Tauronizer** pojawi się w menu
   bocznym Home Assistant.

Dodatek buduje obraz lokalnie na urządzeniu (nie wymaga gotowego obrazu w
rejestrze). Obsługiwane architektury: `amd64` i `aarch64`.

### Uprawnienia

- `homeassistant_api: true` — dostęp do REST API i WebSocket Home Assistant
  przez Supervisora. Token Supervisora jest dodawany automatycznie.
- `ingress: true` — panel działa w iframe Home Assistant; nie trzeba
  osobnego portu ani logowania.
- `panel_admin: false` — panel widzą także użytkownicy niebędący adminami.
  Oznacza to, że każdy, kto ma dostęp do panelu, widzi historię zużycia i
  może zmieniać taryfy. W razie potrzeby ustaw `panel_admin: true` w
  `config.yaml` i przebuduj dodatek.

## Jak korzystać

1. **Analiza** — wybierz encję energii (sensor z `device_class: energy` lub
   `state_class: total_increasing`), zakres dat i taryfy do porównania.
2. Kliknij **Analizuj zużycie**. Wynik pokaże najtańszą taryfę, koszt w
   okresie, szacunek roczny oraz rozbicie na strefy i składniki rachunku.
3. **Taryfy** — dostosuj stawki do swojej umowy. Możesz edytować preset
   (zmiany są lokalne), zduplikować go jako własną taryfę albo utworzyć
   nową. **Przywróć presety** cofa edycje presetów do wartości domyślnych.
4. **Historia** — podgląd i usuwanie zapisanych analiz.

### Strefy czasowe

Strefa pasuje, gdy spełnione są jednocześnie: miesiąc (jeśli podano), dzień
tygodnia, przedział godzinowy i wyjątek świąteczny. **Pierwsza pasująca
strefa wygrywa**, dlatego ostatnia strefa powinna pokrywać całą dobę.

- Godziny muszą być pełne, format `06:00-13:00`; doba to `00:00-24:00`.
- `months` (1–12) opcjonalnie ogranicza strefę do części roku — tak działa
  sezonowy szczyt w G13.
- „Święta traktuj jak pozaszczyt” wyłącza strefę w polskie dni ustawowo
  wolne (z Wielkanocą, Zielonymi Świątkami i Bożym Ciałem).
- Walidacja odrzuca taryfę, która nie pokrywa całego roku, wszystkich dni i
  godzin (z uwzględnieniem świąt).

### Wbudowane taryfy (wartości przykładowe, netto)

| Taryfa | Strefy | Uwagi |
| --- | --- | --- |
| G11 | jedna, cała doba | najprostsza |
| G12 | szczyt: dni robocze 06–13 i 15–22 | weekendy poza szczytem, święta jak dzień roboczy |
| G12w | szczyt: dni robocze 06–13 i 15–22 | weekendy i święta poza szczytem |
| G13 | przedpołudniowy 07–13; popołudniowy zimą 16–21 (X–III), latem 19–22 (IV–IX) | weekendy i święta poza szczytem |

Stawki energii i dystrybucji w presetach są przykładowe. Opłaty stałe i
zmienne (przejściowa, OZE, kogeneracyjna, mocowa) oraz akcyza i VAT są
wspólne dla wszystkich presetów i również podlegają edycji.

## Metodologia i założenia

- **Dane:** godzinowe statystyki długoterminowe Home Assistant
  (`recorder/statistics_during_period`). Zużycie to pole `change`
  przeliczone na kWh (Wh, MWh, GWh, GJ, MJ, kJ, J).
- **Strefy:** przypisanie na podstawie czasu lokalnego `Europe/Warsaw`, z
  poprawną obsługą zmiany czasu (DST), weekendów i polskich świąt.
- **Opłaty stałe:** miesięczne opłaty netto rozliczane proporcjonalnie do
  liczby dni w analizowanym okresie (`dni × 12 / 365,25`).
- **Szacunek roczny:** koszty zmienne skalowane do 365,25 dnia + 12 opłat
  stałych, następnie VAT.
- **VAT:** doliczany do sumy netto (domyślnie 23%). Akcyza i opłaty zmienne
  są liczone od każdej kWh.
- **Ujemne przyrosty** (np. reset licznika) są pomijane; aplikacja pokazuje
  ostrzeżenie. Podobnie ostrzega, gdy statystyki zaczynają się lub kończą
  wcześniej niż wybrany zakres.
- **Brak danych** w zakresie kończy się czytelnym komunikatem — sprawdź
  `state_class` encji i to, czy HA zbiera statystyki długoterminowe.

Wynik jest porównaniem taryf przy założeniu, że profil zużycia się nie
zmienia. Nie uwzględnia prognoz, zmian cen w czasie ani taryf dynamicznych.

## Prywatność i dane

- Dane są przechowywane lokalnie w katalogu dodatku `/data`
  (`tauronizer.db`, SQLite): taryfy, ustawienia i maks. 200 analiz.
- Dodatek komunikuje się wyłącznie z Home Assistant przez Sieć Supervisora.
  Nie wysyła danych na zewnątrz.
- Usunięcie dodatku usuwa też jego dane (katalog `/data` dodatku).

## Rozwój lokalny

Wymagania: Python 3.12+.

```bash
python -m venv .venv
# Windows: .venv\Scripts\activate
# Linux/macOS: source .venv/bin/activate
pip install -r tauronizer/requirements.txt
pip install pytest
```

Testy:

```bash
python -m pytest -q
```

Podgląd bez Home Assistant (deterministyczne dane demo, port 8099):

```bash
python tauronizer/scripts/preview.py
# http://127.0.0.1:8099
```

Baza podglądu trafia do `tauronizer/data-preview/` (ignorowana przez Git).
Aby wymusić czyste dane demo, usuń ten katalog przed uruchomieniem.

### Struktura projektu

```
repository.yaml          # repozytorium dodatków HA
tauronizer/
  config.yaml            # manifest dodatku (Ingress, uprawnienia)
  Dockerfile             # obraz Python 3.12 + uvicorn
  DOCS.md                # dokumentacja widoczna w panelu dodatku
  app/tauronizer/
    main.py              # FastAPI, trasy API, walidacja analizy
    tariffs.py           # presety, strefy, święta, DST
    calc.py              # silnik kosztów i agregacje
    ha_client.py         # REST + WebSocket Home Assistant
    db.py                # SQLite: taryfy, analizy, migracje presetów
    models.py            # modele Pydantic
    static/              # frontend bez frameworków
  scripts/preview.py     # lokalny serwer demo
  tests/                 # pytest
```

### Bezpieczeństwo

- Nagłówki bezpieczeństwa (`X-Content-Type-Options: nosniff`,
  `Referrer-Policy: no-referrer`, `X-Frame-Options: SAMEORIGIN`) są
  ustawiane w aplikacji.
- Token Home Assistant nie jest zapisywany w bazie ani zwracany przez API.
- API nie ma własnego logowania — ochrona pochodzi z Ingress Home Assistant.
  Nie wystawiaj portu 8099 bezpośrednio do Internetu.

## Licencja

Repozytorium jest publiczne, ale kod nie ma licencji open source — wszelkie
prawa zastrzeżone. Możesz zainstalować i używać dodatku na własnym Home
Assistant. Nazwa Tauron należy do jej właściciela; Tauronizer nie jest
powiązany z Tauronem.
