# Prosument w Tauronizerze (DEV)

W formularzu **Analiza → Prosument** wybierz sposób rozliczenia i encję eksportu.
Główna encja analizy musi mierzyć **pobór z sieci**, druga **oddawanie do sieci**.
Obie muszą być licznikami energii z godzinowymi statystykami Home Assistant.
Nie wybieraj całkowitego zużycia domu, produkcji falownika ani mocy chwilowej.
Przycisk **Zapisz ustawienia prosumenta** zachowuje wybór w dodatku. Analiza używa
aktualnych ustawień formularza, a jej historia zachowuje kopię tych ustawień.

Dostępne tryby: wyłączony, net-metering z opustem 0,8 lub 0,7, net-billing RCEm
i net-billing RCE. Wybór jest niezależny od taryfy poboru. Dostępność danego
systemu dla konkretnego klienta wynika z umowy — zmiana w kalkulatorze nie zmienia umowy.

## Co liczymy

- Wspólne, prawidłowe godziny poboru i eksportu są bilansowane: różnica dodatnia
  oznacza pobór, ujemna eksport. Profile i kWh analizy pokazują pobór po tym bilansowaniu.
  Brakujący odczyt eksportu nie oznacza zerowego eksportu. Godzina bez jednego
  z dwóch odczytów jest pomijana w obu kierunkach i zgłaszana w kompletności danych.
- Net-metering: eksport tworzy saldo kWh po współczynniku 0,8 lub 0,7. Najpierw
  pokrywane są te same strefy, a nadwyżka kolejne strefy, począwszy od najwyższej
  stawki zmiennej dystrybucji. Najstarsze saldo jest wykorzystywane najpierw.
  Opłaty za energię, akcyzę i zmienne składniki dystrybucji dotyczą pozostałego
  poboru; opłaty stałe i mocowa pozostają. Saldo z miesiąca eksportu jest ważne
  do końca odpowiadającego mu miesiąca kolejnego roku.
- Net-billing: eksport jest wyceniany po RCEm lub RCE w zł/MWh (przeliczenie /1000).
  Od eksportu z lutego 2025 r. depozyt zwiększamy o 1,23, wcześniej o 1.
  Ujemne ceny eksportu przyjmujemy jako zero. Depozyt jest dostępny od następnego
  miesiąca, pokrywa energię czynną z akcyzą i VAT, a nie dystrybucję ani opłaty stałe.
  Wygasa po 12 miesiącach od przypisania; wykorzystujemy najstarsze środki.
- Potencjalny zwrot wygasłego depozytu pokazujemy osobno: do 20% pierwotnej
  wartości eksportu dla RCEm, do 30% dla RCE od nowych zasad (bez mnożnika 1,23).
  Nie zmniejsza kwoty do zapłaty i nie jest gwarancją wypłaty przez sprzedawcę.

Dla każdej taryfy **Szczegóły rachunku → Rozliczenie prosumenta** pokazują kolejne
miesiące: pobór, eksport, utworzone i wykorzystane saldo, wygaśnięcia, saldo końcowe
i kwotę do zapłaty. Ranking oraz wykres kosztów miesięcznych porównują **do zapłaty**.
Najtańsza taryfa na wykresie pozostaje ta sama dla całej analizy.
Saldo końcowe nie jest odejmowane jako oszczędność ani traktowane jako gotówka.
W net-billingu tabela składników i pączek pokazują pełny rachunek przed pokryciem
go z depozytu; w opustach — opłaty za pozostały pobór.

## Saldo początkowe

Opcjonalne wiersze salda odwzorowują stan na początek wybranego zakresu, a nie całą
wartość pierwotnie wygenerowanych środków. Bez nich zakładamy zero i pokazujemy uwagę.
Podaj osobno każdy miesiąc:

- Opusty: pozostałe kWh **już po** współczynniku oraz miesiąc eksportu. Możesz
  wskazać strefę. Miesiąc eksportu musi poprzedzać miesiąc analizy. Bez niej saldo jest wspólną pulą rozliczaną od najdroższej
  dystrybucji, co oznaczamy jako przybliżenie. Gdy wybrana strefa nie istnieje
  w porównywanej taryfie, tej taryfy nie liczymy zamiast zgadywać mapowanie.
- Depozyt: pozostała kwota zł oraz miesiąc przypisania na konto. Miesiąc
  przypisania może być równy miesiącowi rozpoczęcia analizy. Opcjonalna
  pierwotna wartość eksportu przed mnożnikiem pozwala wyznaczyć limit zwrotu.
  Bez niej nie szacujemy zwrotu z tego salda.

Saldo dotyczy konkretnego początku analizy. Po zmianie zakresu sprawdź je ponownie.

## Ceny i ograniczenia

Ceny eksportu są niezależne od stref S1–S4 G14dynamic. Pobieramy je z PSE:
[RCE — API](https://api.raporty.pse.pl/api/rce-pln) oraz
[RCEm — tabela z korektami](https://www.pse.pl/oire/rcem-rynkowa-miesieczna-cena-energii-elektrycznej).
W SQLite przechowujemy ceny, daty publikacji i postęp pobierania. Pełne miesiące RCE
od czerwca 2024 są pobierane raz; po restarcie kontynuujemy przerwane pobieranie.
Bieżące miesiące i około trzy miesiące wstecz są odświeżane co godzinę, z obsługą
korekt. Niepełne starsze miesiące są ponawiane. Tabela RCEm zawiera pełną historię
od 2022 r. i jest odświeżana razem z korektami. Brak ceny potrzebnej do wyceny
nie jest zastępowany zerem: dana taryfa otrzymuje informację o braku obliczenia.
Analiza korzysta z bazy, pobierając brakujące miesiące, jeśli to konieczne.

**RCE jest przybliżeniem:** Home Assistant udostępnia tu godzinowe przyrosty,
więc eksport rozdzielamy równo na cztery kwadranse. Odczyty z HA mogą też różnić
się od bilansowania operatora. Raport pokazuje osobno kompletność obu liczników
i wspólnych godzin. Przy lukach saldo i koszty pozostają niepełnym szacunkiem.

Rozliczenie symulujemy miesięcznie, także dla historii. Historyczne cykle
2/6/12 miesięcy, zmiany umowy i taryfy w środku zakresu oraz indywidualne korekty
faktur nie są odtwarzane. Stawki wybranej definicji taryfy są stałe w całej analizie,
a opłaty miesięczne proporcjonalne do dni według dotychczasowych zasad kalkulatora.
Niepełny miesiąc oznacza saldo tylko dla fragmentu miesiąca. Przeliczenie kosztu
na rok jest proporcją matematyczną, nie prognozą produkcji PV ani wykorzystania depozytu.

Podstawa zasad: [TAURON — strefa prosumenta](https://www.tauron.pl/dla-domu/obsluga-i-pomoc/strefa-prosumenta),
[MKiŚ — pytania i odpowiedzi](https://www.gov.pl/web/klimat/prosument-pytania),
[TAURON — okres rozliczeniowy](https://www.tauron.pl/zmiana-okresu-rozliczeniowego-prosumenta).
