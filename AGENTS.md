# Instrukcje dla agentów kodujących

Dotyczy całego repozytorium. Cel: małe, poprawne zmiany w integracji Home Assistant przy minimalnym czytaniu kontekstu i uruchamianiu tylko istotnych kontroli.

## Szybki start

1. Przeczytaj ten plik oraz tylko moduł, testy i tłumaczenia związane z zadaniem.
2. Użyj `rg` do znalezienia symbolu, przepływu lub istniejącego testu przed otwieraniem dużych plików. Nie czytaj ponownie README ani całego repo, jeśli zadanie tego nie wymaga.
3. Sprawdź `git status --short`; nie nadpisuj zmian użytkownika.
4. Zidentyfikuj istniejący wzorzec i rozszerz go małym patchem. Nie refaktoruj sąsiednich obszarów bez potrzeby.
5. Po zmianie uruchom tylko testy/linter odpowiadające zmienionemu obszarowi. Raportuj dokładnie, co uruchomiono i wynik.

## Branch, PR i wydania

- Każdą zmianę implementacyjną wykonuj na osobnym branchu; nie commituj bezpośrednio do `main`. Nazwę branchu twórz z prefiksem `codex/` i krótkim opisem zadania.
- Po implementacji i lokalnej weryfikacji otwórz Pull Request do `main`, z krótkim opisem zmiany i wyników kontroli.
- Nie scalaj PR, dopóki wymagane kontrole CI dla tego PR nie zakończą się powodzeniem. Po zielonym CI scal PR zgodnie z ustawieniami repozytorium. Jeśli CI nie przechodzi, popraw przyczynę i poczekaj na ponowne zielone CI przed scaleniem.
- Dla każdej zmiany wpływającej na wydanie dobierz i podbij wersję zgodnie z Semantic Versioning (`MAJOR.MINOR.PATCH`): `PATCH` dla kompatybilnych poprawek, `MINOR` dla kompatybilnych nowych funkcji, `MAJOR` dla zmian niekompatybilnych. W tej integracji wersję utrzymuj w `custom_components/alerts_assistant/manifest.json`.
- Nie podbijaj wersji przy zmianach wyłącznie w dokumentacji, instrukcjach lub testach, które nie zmieniają produktu. Przy niejednoznacznym wpływie oceń kompatybilność publicznego zachowania i wybierz wyższy właściwy poziom.
- Wersja początkowa integracji to `1.0.0`; kolejne zmiany produktu wymagają odpowiedniego bumpa względem aktualnej wersji.

## Projekt i granice modułów

To niestandardowa integracja Home Assistant „Alerts Assistant” (HA 2025.6+; Python 3.13) oraz dołączona karta Lovelace. Jeden config entry jest hubem, a alerty są niezależnymi config subentries.

- `custom_components/alerts_assistant/config_flow.py` — config flow, formularze i walidacja subentries, selektory oraz sugestie domyślne.
- `custom_components/alerts_assistant/alert.py` — cykl życia alertu, obserwowanie stanów, powiadomienia, potwierdzanie i harmonogram powtórek.
- `custom_components/alerts_assistant/__init__.py` — setup/unload, rozwiązywanie członków etykiet, synchronizacja encji oraz rejestracja karty i usług.
- `custom_components/alerts_assistant/sensor_utils.py` — klasyfikacja stanu sensorów; współdzielona przez flow i setup.
- `custom_components/alerts_assistant/const.py` — wspólne klucze konfiguracji, domena i stałe.
- `custom_components/alerts_assistant/www/alerts-assistant-card.js` — samodzielna karta Lovelace w czystym JavaScript; nie zakładaj bundlera.
- `custom_components/alerts_assistant/strings.json`, `translations/en.json`, `translations/pl.json` — teksty formularzy, błędy i tłumaczenia; zachowuj zgodność kluczy i obu języków.
- `tests/conftest.py` — wspólne fixture'y `alert_config` i `make_entry`.
- `tests/test_alert.py`, `test_config_flow.py`, `test_init.py`, `test_sensor_utils.py`, `test_translations.py` — testy Python pogrupowane zgodnie z odpowiednimi modułami.
- `tests/frontend-card.test.mjs` — testy karty Node; `tests/ha-addon.e2e.spec.mjs` — E2E przez Playwright i Home Assistant.

## Reguły implementacji

- Zachowuj niezależność alertów: edycja, usunięcie, potwierdzenie lub reload jednego subentry nie może zakłócić pozostałych.
- Przestrzegaj semantyki HA: `turn_off` potwierdza/wycisza, `turn_on` ponownie uzbraja, `toggle` zmienia potwierdzenie; `idle`, `on`, `off` oznaczają odpowiednio bezczynny, aktywny niepotwierdzony i aktywny potwierdzony alert.
- Zmiany formularzy i konfiguracji sprawdzaj również pod kątem migracji/ustawień już zapisanych przez użytkowników. Zachowuj kompatybilność starszych kluczy, jeśli kod już ją zapewnia.
- Stan HA jest tekstem. Używaj wspólnej klasyfikacji z `sensor_utils.py`; traktuj `unknown`/`unavailable` i metadane dokładnie tak jak w istniejącym kodzie.
- Dla tekstów widocznych dla użytkownika aktualizuj wszystkie wymagane zasoby EN i PL oraz sprawdzaj ich zgodność. Nie duplikuj tekstów tłumaczeń w kodzie, jeśli HA udostępnia odpowiedni mechanizm.
- Karta renderuje dane encji w HTML: zachowuj escaping i bezpieczne tworzenie elementów. Nie wprowadzaj frameworka ani procesu build bez konkretnej potrzeby.
- Trzymaj się formatowania Ruff (88 kolumn; selekcje E/F/W/I/UP/B/SIM/BLE). Nie dodawaj zależności bez uzasadnionej konieczności.
- Dodawaj/zmieniaj testy tylko dla zachowania objętego zmianą, zgodnie z konwencjami istniejącego testu. Unikaj testów e2e, jeśli wystarcza test jednostkowy/integracyjny.

## Weryfikacja według zakresu

Nie uruchamiaj całego CI domyślnie. Wybierz najwęższą adekwatną kontrolę; rozszerz ją, gdy zmiana przekracza jeden obszar lub zadanie wymaga pełnego sprawdzenia.

- Python: `python -m pytest -q tests/test_<moduł>.py` (w Windows użyj `.venv\Scripts\python.exe -m pytest -q ...`, jeśli środowisko jest dostępne).
- Windows: wszystkie testy uruchamiaj przez WSL, zgodnie z README; nie odpalaj pytest, testów Node ani Playwright natywnie w PowerShell. Przejdź w WSL do repozytorium pod `/mnt/c/Users/<user>/Documents/ChatGPT/alerts_assistant`, a następnie użyj poleceń z README (`python3 -m pytest ...`, `node --test ...`, `npm run test:ha`). E2E dodatkowo wymaga Node.js 22, Playwright/Chromium oraz Docker Desktop z integracją WSL.
- Flow lub integracja: `python -m pytest -q tests/test_config_flow.py tests/test_init.py`.
- Alert i cykl życia: `python -m pytest -q tests/test_alert.py`.
- Tłumaczenia: `python -m pytest -q tests/test_translations.py`.
- Python lint/format: `ruff check <zmienione pliki .py>` oraz `ruff format --check <zmienione pliki .py>`.
- Karta: `node --test tests/frontend-card.test.mjs`.
- E2E Home Assistant: `npm run test:ha` tylko dla zmian wymagających rzeczywistego HA, konfiguracji flow lub interakcji karty; wymaga Node.js 22, Playwright/Chromium i Docker.
- Pełna kontrola CI (gdy wymagana lub uzasadniona szeroką zmianą): Ruff, `pytest -q --cov --cov-report=term-missing --cov-fail-under=90`, testy Node i HA E2E, Hassfest oraz HACS. Nie deklaruj wykonania kontroli, których nie uruchomiono.

## Oszczędzanie tokenów i raport

- Odpowiadaj na podstawie konkretnego zakresu zmiany; nie streszczaj ponownie projektu ani README.
- Używaj wyszukiwania symboli i fragmentów plików, zamiast wypisywać duże pliki lub pełny log. Przy błędzie pokaż tylko istotny fragment.
- Nie twórz planu wieloetapowego dla małej poprawki. Dla większej zmiany podaj krótko zakres i zależności, a następnie implementuj.
- Nie wykonuj powtórnie kontroli, która już przeszła, jeśli kod objęty nią się nie zmienił.
- Końcowy raport ma zawierać: co zmieniono (z plikami), kontrole uruchomione i wynik oraz znane ograniczenia/nieuruchomione istotne kontrole. Bądź zwięzły.
