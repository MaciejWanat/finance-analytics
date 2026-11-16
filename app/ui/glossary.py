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
    "drawdown": (
        "Spadek od szczytu: o ile procent portfel był poniżej swojego najwyższego wcześniejszego poziomu. "
        "Liczony na TWR, więc nowe wpłaty nie ukrywają spadków."
    ),
    "drawdown_current": "O ile procent portfel jest dziś poniżej swojego najwyższego poziomu w wybranym okresie.",
    "monthly_returns": "TWR całego portfela w każdym miesiącu kalendarzowym i w każdym roku.",
    "result_period": (
        "Zmiana wartości portfela w okresie po odjęciu wpłat i dodaniu wypłat, czyli to, co faktycznie zarobiłeś "
        "w złotych. Procent obok to TWR."
    ),
    "total_gain": "Wartość portfela minus wpłacony kapitał: łączny zysk od początku historii.",
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
    "trend_90": "Wartość pozycji w PLN w ostatnich 90 dniach.",
    "allocation": "Podział dzisiejszej wartości portfela według wybranej kategorii.",
    "composition": "Wartość każdej części portfela na koniec tygodnia lub miesiąca, ułożona w słupek.",
    "asset_class": "Rodzaj aktywa: akcje, ETF (fundusz notowany na giełdzie), gotówka, obligacje.",
    "etf": "ETF to fundusz notowany na giełdzie, zwykle odwzorowujący indeks (np. S&P 500, MSCI World).",
    "cash": "Wolne środki na rachunku maklerskim, w walucie rachunku.",
    # --- periods ------------------------------------------------------------------------------
    "periods": (
        "1M: ostatni miesiąc. 3M: trzy miesiące. YTD: od początku bieżącego roku. 1R: ostatni rok. "
        "3L: trzy lata. Maks.: cała historia."
    ),
    "breakdown": "Według czego podzielić portfel na wykresach poniżej.",
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
        "GUS publikuje inflację za dany miesiąc w połowie następnego. Dla nowszych miesięcy aplikacja zakłada "
        "brak zmiany cen (ostatni znany poziom), więc wynik realny jest wtedy przybliżony."
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
    # --- inbox ----------------------------------------------------------------------------------
    "inbox": (
        "Folder, do którego zapisujesz eksporty z xStation. Aplikacja sprawdza go co minutę i kopiuje nowe pliki "
        "do własnego katalogu danych, więc nie musisz ich importować ręcznie. Działa bez internetu."
    ),
    # --- network --------------------------------------------------------------------------------
    "offline": "Aplikacja nie łączy się z internetem i liczy wszystko na już zapisanych danych.",
    "online": (
        "Aplikacja odświeża ceny i kursy. Wysyła wyłącznie tickery, kody walut i daty, nigdy kwoty, ilości "
        "ani numery rachunków."
    ),
}
