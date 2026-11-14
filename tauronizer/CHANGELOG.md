# Historia zmian

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
