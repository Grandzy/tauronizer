# Historia zmian

## Niewydane

- Zakładka „Ustawienia” zastępuje „Sensory”: na górze wybór licznika energii i konfiguracja prosumenta, poniżej ustawienia i statusy sensorów Home Assistant. Analiza zawiera zakres dat, wybór taryf i podsumowanie używanych ustawień.

- Obsługa prosumentów: net-metering 0,8/0,7, net-billing RCEm i RCE, osobna encja eksportu, zapisywane ustawienia i miesięczne salda początkowe.
- Rozliczenie każdej taryfy miesiąc po miesiącu: wykorzystanie i wygaśnięcie opustów/depozytu, potencjalny zwrot, saldo końcowe i kwota do zapłaty. Ranking i wykres miesięczny uwzględniają rozliczenie prosumenta.
- Lokalna baza oficjalnych cen eksportu PSE: historia RCE i RCEm, aktualizacje i korekty, wznawianie pobierania. Ceny eksportu są niezależne od Kompasu G14dynamic.
- Kompletność obu liczników i wspólnych godzin, bilansowanie godzinowe, ostrzeżenia o zerowym saldzie początkowym i przybliżeniu RCE z godzinowych danych HA.

- Wersja testowa ma osobne oznaczenie DEV w nazwie repozytorium, dodatku i panelu Home Assistant.
- Najechanie na wycinek wykresu pączkowego faktury podświetla odpowiadający mu wiersz legendy; działa także przy wyborze klawiaturą i osobno dla każdej taryfy.
- Szersza tabela zużycia według stref i węższa kolumna składników rachunku; długie nazwy stref zawijają się zamiast wymuszać przewijanie poziome.

## 0.4.6 — 15.11.2026

- Minimalistyczne podpowiedzi na wykresach słupkowych: kropka w kolorze słupka i sama wartość z jednostką, bez dodatkowego tekstu.
- Najechany lub wybrany klawiaturą słupek delikatnie się rozjaśnia. Podpowiedzi nie są ucinane przez przewijany wykres.
- „Profil zużycia”: pole powiększa się i pokazuje skumulowaną wartość z dwoma miejscami po przecinku, bez jednostki, w kompaktowym okienku.
- Ujednolicono nieprzezroczyste tła obu heatmap, także po powiększeniu; sąsiednie pola nie prześwitują przez aktywne pole.

## 0.4.5 — 15.11.2026

- Węższe słupki kosztów miesięcznych i podpowiedzi z wartościami zużycia po najechaniu na słupek.

- Wykres pączkowy struktury faktury w szczegółach każdej taryfy, z osobnymi opłatami, akcyzą, VAT oraz legendą kwot i udziałów. Starsze analizy korzystają z dostępnych sum zbiorczych.

- Raport kompletności godzin zużycia: procent, miesiące, lista luk i ostrzeżenia na wykresach. Uwzględnia zmianę czasu i nie liczy przyszłych godzin jako braków.
- Harmonogram G14dynamic na dziś i jutro z nazwami stref, cenami zmiennymi brutto i oznaczeniem nieopublikowanych godzin.
- Sensor MQTT czasu następnej potwierdzonej zmiany strefy G14dynamic, z nazwą kolejnej strefy w atrybutach; bez zgadywania zmian po lukach.

- Sensory MQTT diagnostyki API Kompasu PSE: czas ostatniego pobrania i zapisu danych oraz binarny status połączenia.
- Podgląd diagnostyki w Sensorach, niezależny od wyboru taryfy i dostępności aktualnej strefy.
- Data aktualizacji pozostaje w bazie po restarcie i błędach; status połączenia wymaga nowego sprawdzenia po restarcie i wygasa po 30 minutach bez sprawdzenia.

## 0.4.1 — 15.11.2026

- Heatmapa zużycia według miesięcy i dni tygodnia, z rozróżnieniem lat i brakujących statystyk.
- Miesięczne porównanie pełnego kosztu brutto obecnej taryfy z Sensorów i najtańszej w całej analizie, z obiema nazwami w legendzie.
- Porównanie uwzględnia obecną taryfę również poza zaznaczoną listą, częściowe miesiące i wspólny próg mocowej z całego okresu.
- Wyniki miesięczne zapisują się w historii wraz z taryfą obowiązującą w chwili analizy.

## 0.4.0 — 15.11.2026

- Nowa zakładka **Sensory** z trwałym wyborem obecnej taryfy.
- **`sensor.tauronizer_strefa`** publikuje dokładną nazwę aktualnej strefy.
- **`sensor.tauronizer_cena_kwh`** publikuje pełną cenę zmienną za kWh: energia, dystrybucja, wszystkie opłaty zmienne i akcyza; opcjonalnie VAT. Wybór **netto/brutto** jest zapamiętywany.
- Preset **G14dynamic** z czterema stawkami dystrybucji według Kompasu PSE i stałą ceną energii z cennika TAURON 2026.
- Opisy S1–S4 w definicjach stref, rozwijana legenda na karcie taryfy i objaśnienia w edytorze.
- Pełny import publicznej historii Kompasu do SQLite, zapis postępu i wznowienie po restarcie. Następnie aktualizacje przyrostowe co 15 minut, z obsługą korekt i luk.
- Analizy i sensory korzystają z lokalnej bazy, z rozróżnieniem powtarzających się godzin przy zmianie czasu. Brak danych jest sygnalizowany; nie zastępujemy go najtańszą strefą.
- Status archiwum i przycisk **Uzupełnij dane** w zakładce Taryfy.
- Aktualne presety mają abonament 0 zł, zgodnie z zaprzestaniem naliczania od 1.10.2026. Własne taryfy i edytowane presety są zachowywane.


## 0.3.1 — 14.11.2026

- Dodano oznaczenie „Pozostałe godziny — strefa domyślna” i checkbox w edytorze.
- Strefa domyślna jest zawsze sprawdzana ostatnia, także w istniejących taryfach.
- Zablokowano zmianę jej harmonogramu i odrzucono konfiguracje z dwiema strefami domyślnymi.
- Nowe strefy trafiają przed strefę domyślną; zapis API normalizuje kolejność.
- Dodano testy kolejności, walidacji i zapisu przez API.
- Uzupełniono główne README o screenshot analizy na danych demonstracyjnych i disclaimer AI.

## 0.3.0 — 14.11.2026

- Zaktualizowano presety G11, G12, G12w i G13 według taryf TAURON Sprzedaż
  i TAURON Dystrybucja na 2026 rok, z opłatą jakościową od 1 lutego 2026.
- Zastąpiono błędną opłatę mocową za kWh miesięcznym ryczałtem zależnym
  od czterech progów zużycia. Dodano edycję stawek i poboru kwalifikującego;
  bez wpisanego poboru próg jest szacowany z analizowanego okresu.
- Uzupełniono opłatę jakościową, poprawiono OZE i kogeneracyjną oraz
  usunięto opłatę przejściową.
- Poprawiono strefy G12 w weekendy, ceny stref G13 oraz kalendarz świąt
  o Wigilię od 2025 roku.
- Doprecyzowano ceny netto bez akcyzy w edytorze i rozbicie rachunku:
  osobna opłata mocowa, suma netto, VAT i końcowa kwota brutto.
- Poprawiono ochronę edytowanych presetów przed nadpisaniem podczas
  kolejnych aktualizacji.
- Dodano testy progów, podatków, zapisu konfiguracji i aktualizacji presetów.

Presety domyślnie przyjmują 3 fazy, abonament w cyklu miesięcznym i brak
opłaty handlowej. Nie obejmują TAURON Sprzedaż GZE ani ofert rynkowych.
Symulacja stosuje jeden cennik i jeden próg mocowej w całym okresie.

Po aktualizacji sprawdź własne taryfy i edytowane presety: zachowują stare
wartości. „Przywróć presety” zastępuje edycje nowymi definicjami.
Zapisane analizy pozostają bez zmian.
