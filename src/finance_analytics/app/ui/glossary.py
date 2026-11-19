"""Plain-language explanations of every term that may not be obvious (Polish UI copy).

One source for all tooltips, so the same word is always explained the same way.
Use `G["twr"]` for `help=` of KPIs, section headings, filters and table columns.
"""

from __future__ import annotations

G: dict[str, str] = {
    # --- returns and risk -------------------------------------------------------------------
    "twr": (
        "TWR (stopa zwrotu ważona czasem) mówi, ile zarobiły same inwestycje, bez wpływu tego, kiedy i ile "
        "wpłacałeś. Tak podają wyniki fundusze, więc da się go porównać z rynkiem."
    ),
    "twr_annual": "TWR przeliczony na rok (średnio rocznie). Pokazywany tylko dla okresów od roku.",
    "xirr": (
        "XIRR (stopa ważona kapitałem) to Twój roczny zysk z uwzględnieniem dat i kwot wpłat i wypłat: "
        "oprocentowanie lokaty, która z tych samych wpłat dałaby Ci dziś tę samą kwotę. "
        "Pokazywany dla okresów od roku."
    ),
    "xirr_tile": (
        "Ile średnio rocznie zarabia Twój portfel w wybranym okresie, z uwzględnieniem dat i kwot wpłat i wypłat "
        "(XIRR): oprocentowanie lokaty, która z tych samych wpłat dałaby Ci dziś tę samą kwotę. Łatwo porównać z "
        "inflacją albo lokatą. Pod spodem ta sama stopa realnie (po inflacji) albo, z włączonym „Po inflacji”, "
        "nominalnie. Okres krótszy niż rok też jest przeliczany na rok, więc liczby bywają bardzo duże: +4% w miesiąc "
        "to ok. +60% rocznie, a +1% w jeden dzień to kilka tysięcy procent."
    ),
    "xirr_none": "Dla tego okresu nie da się policzyć stopy, np. bez wartości na jego początku i bez wpłat.",
    "drawdown": (
        "Spadek od szczytu: o ile procent portfel był poniżej swojego najwyższego wcześniejszego poziomu. "
        "Liczony na TWR, więc nowe wpłaty nie ukrywają spadków."
    ),
    "profit_ratio": (
        "Zysk całkowity jako procent wpłaconych pieniędzy: (wartość portfela − wpłaty) / wpłaty. Np. wpłaciłeś "
        "1000 zł, masz 1250 zł: +25%. Pod spodem to samo po inflacji, z wpłatami w dzisiejszych złotych."
    ),
    "balance_edit": (
        "Tabela działa jak arkusz: zmieniasz konto, datę, kwotę albo notatkę w komórce, dodajesz wiersz na dole "
        "i usuwasz zaznaczony ikoną kosza. „Zapisz zmiany” sprawdza całą tabelę i nadpisuje plik "
        "cash_balances.csv; wycena i wpłaty przeliczają się od nowa. Kwoty wpisuj z kropką (12345.67)."
    ),
    "fx_result": (
        "Ile zarobiłeś (+) albo straciłeś (−) na samych kursach walut w wybranym okresie: akcje, ETF-y i gotówka "
        "w USD, EUR i innych walutach. Każdego dnia wartość w walucie razy zmiana kursu NBP; od zakupu do dziś to "
        "dokładnie różnica między dzisiejszym kursem a kursem z dnia zakupu. Po sprzedaży zostaje część zrealizowana. "
        "Ruchy samych cen akcji tu nie wchodzą."
    ),
    "real_view": (
        "Pokazuje całą stronę w dzisiejszych złotych: każdą wartość, wpłatę i koszt przeliczone wskaźnikiem cen GUS "
        "od swojego dnia do dziś. Wynik, TWR i zysk do wpłat są wtedy realne, czyli po odjęciu inflacji."
    ),
    "real_view_no_cpi": "Brak danych o inflacji (CPI z GUS): pobierz je na stronie Dane rynkowe.",
    "underwater": (
        "Jak głęboko portfel był pod kreską względem wpłaconych pieniędzy: najniższa wartość "
        "(wartość portfela − wpłaty) / wpłaty w wybranym okresie. Np. wpłaciłeś 1000 zł, najmniej miałeś 800 zł, "
        "dziś 1200 zł: tu −20%. Wartość dodatnia znaczy, że portfel nigdy nie był poniżej wpłat."
    ),
    "drawdown_current": "O ile procent portfel jest dziś poniżej swojego najwyższego poziomu w wybranym okresie.",
    "monthly_returns": "TWR całego portfela w każdym miesiącu kalendarzowym i w każdym roku.",
    "result_period": (
        "Zmiana wartości portfela w okresie po odjęciu wpłat i dodaniu wypłat, czyli to, co faktycznie zarobiłeś "
        "w złotych. Procent obok to TWR."
    ),
    "beat_market": (
        "Czy w wybranym okresie zarobiłeś więcej, niż gdybyś po prostu kupował indeks S&P 500 (500 największych "
        "spółek z USA, z reinwestowanymi dywidendami, przeliczony na złote po kursie NBP). Porównanie to portfel-cień: "
        "na początku okresu ma w indeksie tyle, ile był wart Twój portfel, a każdą Twoją wpłatę wydaje na indeks tego "
        "samego dnia (wypłatę bierze ze sprzedaży indeksu). Kwota to różnica między Twoim portfelem a tym cieniem: "
        "plus znaczy, że Twoje wybory (spółki, obligacje, gotówka, waluty, moment zakupów) dały więcej niż indeks, "
        "minus, że prosty fundusz na S&P 500 dałby więcej. Wykres pokazuje, jak ta różnica zmieniała się w czasie."
    ),
    "beat_market_missing": (
        "Brak notowań indeksu S&P 500 za ten okres. Pobierz dane rynkowe na stronie Dane rynkowe: indeks "
        "pobiera się razem z cenami Twoich instrumentów."
    ),
    "beat_market_waiting": (
        "Indeks S&P 500 nie ma jeszcze notowania zamknięcia w tym okresie (sesja w USA trwa albo jeszcze się nie "
        "zaczęła). Porównanie pojawi się po zamknięciu sesji i pobraniu danych rynkowych; dłuższy okres pokaże "
        "wynik do ostatniego zamknięcia."
    ),
    "total_gain": "Wartość portfela minus wpłacony kapitał: łączny zysk od początku historii.",
    "today": (
        "Dzisiejszy zysk lub strata: zmiana wartości portfela od zamknięcia poprzedniej sesji, bez wpłat i wypłat. "
        "Duża liczba to procent (TWR dnia), plakietka to kwota w złotych. W weekend, w święto i zanim pobierzesz "
        "dzisiejsze notowania widać ostatnią sesję."
    ),
    "contributed": "Suma wszystkich wpłat minus wypłaty, przeliczona na PLN po kursie NBP z dnia operacji.",
    "portfolio_value": "Wartość wszystkich pozycji i gotówki na wszystkich rachunkach, w PLN.",
    # --- stocks vs currency -----------------------------------------------------------------
    "attribution": (
        "Rozbicie wyniku w PLN: (1 + wynik) = (1 + ceny) × (1 + waluty) × (1 + pozostałe). Mnożymy, a nie "
        "dodajemy, bo stopy zwrotu się składają."
    ),
    "part_price": "Wynik ze zmiany cen akcji i ETF w ich własnej walucie (np. w USD), przy stałym kursie walut.",
    "part_fx": (
        "Wynik ze zmiany kursu złotego wobec walut, w których notowane są Twoje instrumenty i w których "
        "trzymasz gotówkę."
    ),
    "part_other": (
        "Wszystko poza cenami i walutami: dywidendy, odsetki od wolnych środków, podatki, opłaty oraz różnica "
        "między ceną zakupu a ceną zamknięcia w dniu zakupu."
    ),
    "fx_sign": (
        "Wynik z kursu zależy od tego, ile w danej walucie miałeś, gdy kurs się zmieniał. Może więc mieć inny "
        "znak niż zmiana kursu w całym okresie, np. gdy dokupowałeś przy niskim kursie, a potem kurs wzrósł."
    ),
    # --- positions and valuation -------------------------------------------------------------
    "ticker": "Skrót instrumentu na giełdzie. Sufiks oznacza giełdę: .US to USA, .UK to Londyn.",
    "cost": "Ile zapłaciłeś za pozycje, które nadal masz, w PLN po kursie NBP z dnia zakupu.",
    "pnl": "Wartość dziś minus koszt zakupu (zysk lub strata niezrealizowana, przed podatkiem).",
    "share": "Jaką część wartości całego portfela stanowi ta pozycja.",
    "last_price": "Ostatnia cena zamknięcia w walucie instrumentu; w trybie online cena z ostatniego odświeżenia.",
    "trend_90": "Wynik pozycji (wartość minus koszt) w PLN w ostatnich 90 dniach. Dokupienie akcji nie wygina linii.",
    "allocation": "Podział dzisiejszej wartości portfela według wybranej kategorii.",
    "composition": "Wartość każdej części portfela na koniec tygodnia lub miesiąca, ułożona w słupek.",
    "asset_class": (
        "Rodzaj aktywa: akcje, ETF (fundusz notowany na giełdzie), metale szlachetne, obligacje, gotówka. "
        "Metale szlachetne to ETC, ETN i ETF z nazwą kruszcu (złoto, srebro, platyna, pallad); fundusze "
        "spółek wydobywczych zostają w ETF. Inne to pozostałe ETC i ETN, np. na bitcoina albo ropę. "
        "Klasę pojedynczego tickera zmienisz w pliku config/instruments.yaml w katalogu danych."
    ),
    "etf": "ETF to fundusz notowany na giełdzie, zwykle odwzorowujący indeks (np. S&P 500, MSCI World).",
    "cash": "Wolne środki na rachunku maklerskim, w walucie rachunku.",
    # --- periods ------------------------------------------------------------------------------
    "periods": (
        "1D: dzień z kafelka „Dzisiaj”, co 5 minut. 1T: ostatni tydzień (7 dni). 1M: ostatni miesiąc. "
        "3M: trzy miesiące. YTD: od początku bieżącego roku. 1R: ostatni rok. 3L: trzy lata. Maks.: cała historia."
    ),
    "breakdown": "Według czego podzielić portfel na wykresach poniżej.",
    "intraday": (
        "Wartość portfela w ciągu dnia z kafelka „Dzisiaj”, co 5 minut, razem z pre-market i post-market w USA. "
        "Każda pozycja zmienia się z ceną instrumentu i kursem waluty, a ostatni punkt to dzisiejsza wycena. Przed "
        "otwarciem giełdy jej instrumenty stoją na poprzednim zamknięciu. Przerywana linia to wartość na "
        "zamknięciu, od którego liczy się dzisiejszy wynik. Skład portfela jest ten z końca dnia przez cały dzień."
    ),
    "intraday_fetch": (
        "Pobiera z Yahoo 5-minutowe notowania posiadanych instrumentów i kursy walut z ostatnich 5 dni. Wysyła "
        "tylko tickery. Jednorazowo: w trybie offline aplikacja sama nic nie pobiera."
    ),
    # --- currencies and market data -------------------------------------------------------------
    "nbp_rate": (
        "Kurs średni NBP (tabela A), publikowany w dni robocze ok. 12:00. Stosowany do wyceny historii, kosztów "
        "i rozliczeń podatkowych."
    ),
    "fx_change": "Zmiana kursu średniego NBP waluty w okresie, w którym instrument był w portfelu.",
    "price_change": "Zmiana ceny instrumentu w jego walucie w okresie, w którym był w portfelu.",
    "quotes": "Liczba dni z zapisanym notowaniem w lokalnej bazie.",
    "split": (
        "Split to podział akcji (np. 1 akcja na 10 tańszych). Ceny z Yahoo są wtedy korygowane wstecz, "
        "więc aplikacja przelicza też liczbę akcji."
    ),
    "yahoo_ticker": "Ticker w Yahoo Finance, z którego pobierane są ceny. Powstaje z tickera XTB.",
    "last_error": "Ostatni błąd przy pobieraniu danych; puste pole oznacza, że ostatnie pobranie się udało.",
    # --- accounts and imports -------------------------------------------------------------------
    "ike": "IKE (Indywidualne Konto Emerytalne): zyski zwolnione z podatku Belki przy wypłacie po 60. roku życia.",
    "ikze": (
        "IKZE (Indywidualne Konto Zabezpieczenia Emerytalnego): wpłaty odliczasz od podstawy podatku, a wypłata "
        "po 65. roku życia jest opodatkowana ryczałtem 10%."
    ),
    "account_kind": "Zwykły rachunek maklerski albo rachunek z ulgą podatkową (IKE, IKZE).",
    "account_cash": "Saldo gotówki: suma wszystkich operacji gotówkowych w walucie rachunku.",
    "wht": (
        "Podatek u źródła (WHT) pobierany przez kraj spółki od dywidendy, np. 15% w USA przy złożonym "
        "formularzu W-8BEN."
    ),
    "position": "Pojedynczy zakup instrumentu. Kilka zakupów tej samej spółki to kilka pozycji.",
    # --- dividends ----------------------------------------------------------------------------
    "dividend_gross": "Dywidenda przed jakimkolwiek podatkiem: tyle spółka wypłaciła na Twoje akcje.",
    "dividend_net": "Dywidenda, która faktycznie wpłynęła na rachunek, po potrąceniu podatku u źródła.",
    "dividend_rate": (
        "Kurs NBP z ostatniego dnia roboczego przed dniem wypłaty (tzw. D-1). Tak przelicza się dywidendy "
        "w zeznaniu podatkowym. Rachunek w PLN dostaje już złotówki, więc tam kurs wynosi 1."
    ),
    "tax_due": (
        "Szacunek podatku do dopłaty w Polsce (zeznanie PIT-38): 19% dywidendy brutto minus podatek "
        "pobrany za granicą, nie mniej niż zero. Na IKE i IKZE nie płacisz go wcale. To szacunek, nie porada "
        "podatkowa."
    ),
    "wht_rate": "Jaka część dywidendy brutto została pobrana jako podatek u źródła.",
    "dividend_yield": (
        "Dywidendy netto z ostatnich 12 miesięcy w relacji do dzisiejszej wartości portfela: ile procent "
        "rocznie dostajesz w gotówce."
    ),
    "dividend_payments": "Liczba wypłat dywidendy (jedna wypłata na rachunek i dzień).",
    # --- inflation ------------------------------------------------------------------------------
    "cpi": (
        "CPI to wskaźnik cen towarów i usług konsumpcyjnych, który co miesiąc publikuje GUS. Pokazuje, o ile "
        "wzrosły ceny koszyka zakupów przeciętnego gospodarstwa domowego."
    ),
    "inflation": (
        "Inflacja w okresie: o ile procent wzrosły ceny między początkiem a końcem okresu (z indeksu CPI "
        "GUS). Tyle musi zarobić portfel, żeby jego siła nabywcza została taka sama."
    ),
    "real_return": (
        "Zwrot realny to zwrot nominalny po odjęciu inflacji: (1 + zwrot nominalny) / (1 + inflacja) − 1. "
        "Mówi, o ile więcej rzeczy możesz kupić za wynik portfela niż na początku."
    ),
    "todays_pln": (
        "Wartości z przeszłości przeliczone na dzisiejszą siłę nabywczą złotego: wartość × poziom cen dziś / "
        "poziom cen wtedy. Dzięki temu widać, czy portfel rósł realnie, a nie tylko nominalnie."
    ),
    "cpi_estimated": (
        "GUS publikuje inflację za dany miesiąc w połowie następnego. Dla nowszych miesięcy aplikacja przyjmuje "
        "ostatnią opublikowaną inflację rok do roku, rozłożoną równo na miesiące, więc wynik realny jest wtedy "
        "przybliżony."
    ),
    "real_profit": (
        "Zysk realny, czyli „na czysto” po inflacji: wartość portfela dziś minus każda wpłata (i wypłata) "
        "przeliczona na dzisiejsze złote według CPI z GUS od jej dnia do dziś. Przykład: 10 000 zł wpłacone, "
        "gdy ceny były o 8% niższe, to dziś 10 800 zł; przy wartości 11 500 zł zysk nominalny wynosi 1 500 zł, "
        "a realny 700 zł. Procent liczony od wpłat w dzisiejszych złotych."
    ),
    "real_xirr": (
        "XIRR liczony na kwotach przeliczonych na dzisiejsze złote: roczny zysk ponad inflację, z uwzględnieniem "
        "dat i kwot wpłat i wypłat. Pokazywany dla okresów od roku."
    ),
    "twr_real": "TWR w wybranym okresie po odjęciu inflacji z tego samego okresu: (1 + TWR) / (1 + inflacja) − 1.",
    "bond_real": (
        "Ile ten zakup zarobił ponad inflację od dnia zakupu: (wartość brutto dziś + wypłacone kupony) / wpłata, "
        "wszystko w dzisiejszych złotych według CPI z GUS, minus 1. Przed podatkiem i opłatą za wcześniejszy "
        "wykup. Wynik dodatni oznacza, że obligacja pobiła inflację."
    ),
    # --- treasury bonds -------------------------------------------------------------------------
    "bond_series": (
        "Seria to skrót obligacji: typ, miesiąc i rok wykupu. EDO0736 to obligacja 10-letnia kupiona "
        "w lipcu 2026 r., wykupywana w lipcu 2036 r."
    ),
    "bond_types": (
        "OTS: 3 miesiące, stałe. ROR: rok, DOR: 2 lata, oprocentowanie za stopą NBP, odsetki co miesiąc. "
        "TOS: 3 lata, stałe. COI: 4 lata, inflacja + marża, odsetki co rok. EDO: 10 lat, ROS: 6 lat, "
        "ROD: 12 lat, inflacja + marża, odsetki dopisywane do kapitału."
    ),
    "bond_edo": (
        "EDO to 10-letnie obligacje emerytalne. Od drugiego roku dają inflację plus marżę, a odsetki co roku "
        "dopisują się do kapitału, więc dostajesz je dopiero przy wykupie."
    ),
    "bond_coi": (
        "COI to 4-letnie obligacje indeksowane inflacją. Od drugiego roku dają inflację plus marżę, a odsetki "
        "są wypłacane co roku na Twoje konto."
    ),
    "bond_margin": (
        "Marża to stała nadwyżka ponad inflację (EDO, COI, ROS, ROD) albo ponad stopę referencyjną NBP "
        "(ROR, DOR), ustalona w dniu zakupu na cały czas trwania obligacji."
    ),
    "bond_current_rate": (
        "Oprocentowanie w bieżącym okresie odsetkowym, w skali roku. W pierwszym okresie jest stałe, potem "
        "zależy od inflacji albo stopy NBP."
    ),
    "bond_avg_rate": "Bieżące oprocentowanie wszystkich obligacji, średnio ważone ich wartością brutto.",
    "bond_rate_source": (
        "Oficjalna: ogłoszona przez Ministerstwo Finansów. Wyliczona: policzona przez aplikację z inflacji GUS "
        "lub stopy NBP, zanim trafiła do pliku z oficjalnymi stopami. Tylko marża: brakuje jeszcze danych o "
        "inflacji, więc odsetki mogą być zaniżone."
    ),
    "bond_period": (
        "Okres odsetkowy to rok (miesiąc w ROR i DOR) liczony od dnia zakupu. Na jego końcu odsetki są "
        "wypłacane albo dopisywane do kapitału, a oprocentowanie może się zmienić."
    ),
    "bond_accrued": (
        "Odsetki naliczone do dziś przed podatkiem: w EDO, ROS, ROD i TOS razem z dopisanymi wcześniej, "
        "w COI, ROR i DOR tylko z bieżącego okresu, bo wcześniejsze już wypłacono."
    ),
    "bond_capitalization": (
        "Kapitalizacja: po każdym roku odsetki dopisują się do wartości obligacji i w kolejnym roku też "
        "zarabiają. Tak działają EDO, ROS, ROD i TOS."
    ),
    "bond_gross": "Wartość nominalna 100 zł za sztukę plus naliczone odsetki, przed podatkiem i opłatą za wykup.",
    "bond_early_fee": (
        "Opłata za wcześniejszy wykup, w złotych za sztukę. W EDO, ROS, ROD i TOS nigdy nie jest wyższa niż "
        "naliczone odsetki; w COI, ROR i DOR tak jest tylko w pierwszym okresie. OTS zwraca wtedy 100 zł bez "
        "odsetek."
    ),
    "bond_payout": (
        "Ile dostałbyś, gdybyś dziś zlecił wcześniejszy wykup: wartość minus opłata i 19% podatku od odsetek "
        "(na IKE bez podatku). Szacunek: bank liczy odsetki jeszcze za kilka dni roboczych po zleceniu."
    ),
    "bond_maturity": "Dzień wykupu: wtedy dostajesz 100 zł za sztukę i pozostałe odsetki.",
    "bond_account": (
        "Rachunek obligacji z pliku accounts.yaml. Pierwszy powstaje sam; dla obligacji na IKE ustaw tam "
        "tax_wrapper: IKE, a aplikacja nie będzie liczyć podatku."
    ),
    "bond_purchase": "Dzień, w którym obligacje zostały zapisane na Twoim rejestrze; od niego liczą się odsetki.",
    "bond_quantity": "Liczba obligacji. Jedna sztuka ma wartość nominalną 100 zł.",
    "bond_flows": (
        "Zakup obligacji to wpłata do portfela, a wypłacone odsetki i wykup to wypłaty z niego, bo trafiają "
        "na konto w banku. Odsetki widać więc w zwrotach w części „pozostałe”."
    ),
    # --- cash at banks --------------------------------------------------------------------------
    "bank_account": (
        "Konto bankowe to konto, na którym trzymasz gotówkę (np. osobiste, oszczędnościowe, walutowe). "
        "Aplikacja nie łączy się z bankiem: saldo wpisujesz sam."
    ),
    "balance": "Saldo to kwota na koncie w jego walucie, w dniu, który wpisałeś. Obowiązuje do kolejnego wpisu.",
    "balance_snapshot": (
        "Snapshot salda to zapisane saldo konta na konkretny dzień. Aplikacja zakłada, że saldo trwa bez zmian "
        "do kolejnego snapshotu, a przed pierwszym konto jeszcze nie istnieje. Im częściej wpisujesz salda, "
        "tym dokładniejszy wykres."
    ),
    "balance_date": (
        "Dzień ostatniego zapisanego salda. Starsze niż 30 dni oznaczamy, bo wartość może już nie być aktualna."
    ),
    "balance_stale": "Ostatnie saldo jest starsze niż 30 dni. Dopisz nowe, żeby gotówka w portfelu była aktualna.",
    "cash_total": "Suma sald wszystkich kont bankowych przeliczonych na PLN po ostatnim kursie NBP.",
    "cash_flows": (
        "Każda zmiana salda między zapisami (wypłata, przelew, odsetki) jest liczona jako wpłata do portfela "
        "albo wypłata z niego. Dzięki temu gotówka nie pokazuje zwrotu, a odsetki z konta oszczędnościowego "
        "nie wchodzą do wyniku. Zmienia się tylko wartość sald w obcych walutach, przez kurs."
    ),
    "csv_export": (
        "Pliki CSV to Twoje dane w prostym formacie, który otworzysz w Excelu. Pobranie zapisuje plik tylko "
        "na tym komputerze. Pusty szablon pokazuje, jak wypełnić plik."
    ),
    "csv_import": (
        "Wgrany plik jest najpierw sprawdzany i pokazany. Poprawne wiersze są dopisywane na koniec Twojego "
        "pliku; nic nie jest nadpisywane, a wiersze z błędami są pomijane."
    ),
    "import_folder": (
        "Wskaż cały folder, który zapisał xStation (także z podfolderami kont). Aplikacja weźmie z niego pliki "
        ".xlsx i .zip, pominie resztę i skopiuje eksporty do własnego katalogu danych. Folder źródłowy zostaje "
        "nietknięty."
    ),
    "import_files": (
        "Plik .zip dokładnie taki, jaki zapisuje xStation, albo wybrane pliki .xlsx. Zip jest rozpakowywany "
        "w pamięci; nic nie trafia poza ten komputer."
    ),
    # --- inbox ----------------------------------------------------------------------------------
    "inbox": (
        "Folder, do którego zapisujesz eksporty z xStation. Aplikacja sprawdza go co minutę i kopiuje nowe pliki "
        "do własnego katalogu danych, więc nie musisz ich importować ręcznie. Działa bez internetu."
    ),
    # --- reset ----------------------------------------------------------------------------------
    "reset": (
        "Usuwa wybrane pliki z katalogu danych aplikacji i czyści z bazy wszystko, co z nich pochodziło. "
        "Ustawienia i folder skrzynki zostają nietknięte. Zanim usuniesz, pobierz kopię zapasową."
    ),
    "market_cache": (
        "Ceny, kursy walut i inflacja zapisane lokalnie. To dane publiczne: po usunięciu można je pobrać "
        "ponownie na stronie Dane rynkowe."
    ),
    # --- network --------------------------------------------------------------------------------
    "offline": (
        "Aplikacja sama nie łączy się z internetem i liczy wszystko na zapisanych danych. Dane rynkowe pobierasz "
        "tylko wtedy, gdy klikniesz przycisk na stronie Dane rynkowe."
    ),
    "online": (
        "Aplikacja odświeża ceny i kursy. Wysyła wyłącznie tickery, kody walut i daty, nigdy kwoty, ilości "
        "ani numery rachunków."
    ),
    "live_status": (
        "Stan cen na żywo. Pulsująca zielona lampka: strumień działa i ceny przychodzą same. Pełna zielona: ceny "
        "odpytywane co ustawiony czas; obok godzina ostatnich cen. Pusta bursztynowa: łączenie. Czerwona: błąd, "
        "aplikacja ponawia próbę. Pusta szara: giełdy i rynek walut są zamknięte."
    ),
    "live_source": (
        "Odpytywanie: aplikacja co ustawiony czas pyta Yahoo o ostatnią cenę każdego instrumentu. Strumień: jedno "
        "stałe połączenie, przez które Yahoo samo przysyła każdą nową cenę, gdy giełda działa. W obu trybach "
        "liczą się też ceny z pre-market i post-market w USA, a wysyłane są tylko tickery."
    ),
    "live_refresh": (
        "Odpytywanie: co ile pobierać ceny, od 2 minut do godziny; częściej Yahoo mogłoby odrzucać zapytania. "
        "Gdy żadna giełda nie działa, a handlują tylko waluty, najwyżej co 5 minut. Strumień: ceny przychodzą "
        "same, a to ustawienie mówi, co ile (od 1 do 60 sekund) odświeżać kafelki, wykres wartości i pozycje na "
        "stronie Portfel. Co 1–2 sekundy strona zużywa wyraźnie więcej procesora niż co 5."
    ),
    "resources": (
        "Ile mocy komputera zużywa sama aplikacja (jej serwer na tym komputerze), mierzone co 5 sekund. Nie "
        "obejmuje karty przeglądarki. Zielony: w normie, bursztynowy: podwyższone, czerwony: wysokie, warto "
        "zmienić ustawienia cen na żywo. Pierwsza minuta po starcie nie jest mierzona: start zawsze dużo kosztuje. "
        "Pomiar zostaje na tym komputerze."
    ),
    "resources_cpu": (
        "Procent jednego rdzenia procesora: aplikacja liczy głównie na jednym rdzeniu, więc 100% znaczy, że jest "
        "nim w pełni zajęta. Pod spodem udział w całym procesorze, jak w menedżerze zadań. Średnia z ostatniej "
        "minuty, więc obejmuje też stronę, z której właśnie przyszedłeś, np. Portfel odświeżany co kilka sekund. "
        "Bursztynowy od 25%, czerwony od 50%."
    ),
    "resources_memory": (
        "Pamięć RAM zajęta przez aplikację i jej udział w całej pamięci komputera. Bursztynowy od 600 MB, "
        "czerwony od 1,2 GB."
    ),
    "resources_feed": (
        "Część rdzenia zużywana przez wątek cen na żywo (odpytywanie albo strumień), średnio z ostatniej "
        "minuty. Przerysowywanie stron liczy się osobno, w kafelku Procesor."
    ),
    "today_tile": (
        "Od północy: nowy dzień zaczyna się o 0:00. Sesjami giełdy w USA: nowy dzień zaczyna się przy otwarciu "
        "sesji (zwykle 15:30), a po zamknięciu wynik zostaje do następnego otwarcia; ruchy walut i innych giełd "
        "między sesjami wliczają się do następnej. Działa, gdy masz instrumenty z USA."
    ),
    "today_us_session": (
        " Dzień liczony sesjami giełdy w USA: zaczyna się przy otwarciu, a po zamknięciu wynik zostaje do "
        "następnego otwarcia. Zmienisz to w Ustawieniach."
    ),
    "today_calendar_day": " Dzień liczony od północy. Zmienisz to w Ustawieniach.",
    "markets": (
        "Lampka pokazuje stan giełdy: pełna zielona – otwarta, pusta – zamknięta, lewa połówka – pre-market, "
        "prawa połówka – post-market. Obok czas do otwarcia, a gdy giełda jest otwarta, do zamknięcia zwykłej "
        "sesji. Sesje w czasie polskim: USA 15:30–22:00 "
        "(pre-market od 10:00, post-market do 2:00), Londyn i Niemcy (Xetra) 9:00–17:30, Warszawa (GPW) "
        "9:00–17:00; przez kilka tygodni wiosną i jesienią USA o godzinę wcześniej. Uwzględnia święta i skrócone "
        "sesje; liczone na tym komputerze, bez internetu."
    ),
}
