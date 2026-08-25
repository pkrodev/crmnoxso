# NOXSO CRM

Jednoosobowy CRM dla firmy NOXSO (branża rolnicza, Wielkopolska).
Specyfikacja projektu: [`CLAUDE.md`](CLAUDE.md).

Stan prac: **etapy 1–6** (fundament, import z normalizacją, ekran klientów,
transkrypcje rozmów, analiza AI, kalendarz), uruchomione i sprawdzone na
prawdziwej bazie 1923 kontrahentów. Etapy 7–8 — SMS i ustawienia — przed nami.

---

## Uruchomienie od zera

### 1. PostgreSQL

Najprościej przez winget — instaluje się bez klikania i bez okna UAC:

```powershell
winget install --id PostgreSQL.PostgreSQL.17 -e --silent `
  --custom "--superpassword TWOJE_HASLO --serverport 5432"
```

Alternatywnie instalator z <https://www.enterprisedb.com/downloads/postgres-postgresql-downloads>
(Windows x86-64). Port zostaw `5432`, Stack Buildera na końcu pomiń.

> Specyfikacja mówi o PostgreSQL 16, ale ta wersja zniknęła już z winget —
> dostępne są 17 i 18. Używamy **17**. Nic w kodzie nie zależy od konkretnej
> wersji major, a Railway również daje 17.

Bazy zakładasz raz:

```powershell
& "C:\Program Files\PostgreSQL\17\bin\psql.exe" -U postgres -f scripts\create_db.sql
```

### 2. Środowisko Pythona

```powershell
python -m venv .venv
.venv\Scripts\python.exe -m pip install -r requirements-dev.txt
```

> **Sieć firmowa blokuje PyPI.** Jeśli instalacja zrywa połączenie
> („Connection interrupted while downloading"), zajrzyj do
> [`wheels/POBIERZ.md`](wheels/POBIERZ.md) — jest tam gotowa lista 75 paczek
> i skrypt, który pobierze je w sieci bez blokady. Instalacja offline:
> ```powershell
> .venv\Scripts\python.exe -m pip install --no-index --find-links wheels -r requirements-dev.txt
> ```

### 3. Konfiguracja

```powershell
Copy-Item .env.example .env
```

W pliku `.env` uzupełnij:

| Zmienna | Skąd wziąć |
|---|---|
| `SECRET_KEY` | `python -c "import secrets; print(secrets.token_hex(32))"` |
| `DATABASE_URL` | hasło z instalacji PostgreSQL |
| `ADMIN_PASSWORD_HASH` | `python scripts\hash_password.py` |

Hasła w postaci jawnej nie zapisujemy nigdzie — ani w kodzie, ani w `.env`.

### 4. Tailwind CLI

Standalone binarka, jeden plik, bez Node'a i bez npm. Pobierasz raz — katalog
`tools\` jest poza repozytorium, bo waży 40 MB:

```powershell
New-Item -ItemType Directory -Force tools | Out-Null
Invoke-WebRequest -OutFile tools\tailwindcss.exe `
  https://github.com/tailwindlabs/tailwindcss/releases/download/v3.4.17/tailwindcss-windows-x64.exe
```

Zbudowany `app/static/css/tailwind.css` **jest** commitowany — Railway nie ma
czym go zbudować. Po zmianach w szablonach przebuduj go i zacommituj na nowo.

### 5. Baza i style

```powershell
$env:FLASK_APP = "wsgi.py"
.venv\Scripts\flask.exe db upgrade
.\scripts\build_css.ps1
```

### 6. Start

```powershell
.venv\Scripts\flask.exe run --debug
```

Aplikacja stoi pod <http://127.0.0.1:5000>.

Podczas pracy nad wyglądem warto trzymać drugie okno z Tailwindem w trybie
obserwowania zmian:

```powershell
.\scripts\build_css.ps1 -Watch
```

---

## Import bazy klientów

Ekran `/import`. Wgrywasz `.ods` albo `.xlsx`, dostajesz **podgląd przed zapisem**
(pierwsze 20 wierszy po normalizacji obok oryginałów + liczniki problemów
policzone na całym pliku), potwierdzasz, a import leci w tle z paskiem postępu.

Co warto wiedzieć:

- **Kolumny rozpoznawane po nagłówkach**, nie po pozycji. Plik produkcyjny ma
  nienazwaną pierwszą kolumnę przesuniętą o jeden wiersz — mapowanie pozycyjne
  przypisałoby klientom cudze numery telefonów.
- **Automatyczne scalanie tylko po akronimie.** Zbieżność NIP-u, telefonu albo
  nazwy oznacza rekord tagiem `mozliwy-duplikat` i zostawia decyzję Tobie —
  w bazie źródłowej 34 NIP-y i 58 numerów należy do odrębnych gospodarstw.
- **Import nigdy nie usuwa danych.** Pusta komórka w nowym pliku nie kasuje
  wartości zapisanej wcześniej.
- Rekordy z nieparsowalnym numerem, błędnym NIP-em lub kodem pocztowym dostają
  tag `do-weryfikacji`, ale **wchodzą do bazy** — nic nie jest odrzucane.

Podgląd normalizacji bez dotykania bazy:

```powershell
.venv\Scripts\python.exe scripts\check_normalization.py "poprawiona baza klientów do dnia 01.03.2022r (1).xlsx"
```

---

## Klienci

Lista pod `/clients`, panel klienta pod `/clients/<id>`.

**Wyszukiwarka szuka jednocześnie po nazwie, akronimie, mieście, NIP-ie,
adresie e-mail i telefonie.** Numer znajdziesz w dowolnym zapisie —
`227503859`, `227-503-859`, `227 503 859`, `+48227503859` i `48227503859`
dają ten sam wynik. Porównujemy też same cyfry kolumny `Phone.raw`, dzięki
czemu odnajdują się również numery, których nie dało się sparsować
(te z `e164 = NULL`).

Filtry: miasto, tag, status, ma-email, ma-telefon. Stronicowanie po 50 rekordów,
po stronie serwera. Wszystko przez HTMX — wpisanie znaku w wyszukiwarce
podmienia samą tabelę, adres w pasku przeglądarki aktualizuje się sam,
więc wynik wyszukiwania da się zabookmarkować i odświeżyć.

W panelu klienta **każde pole edytuje się w miejscu**: kliknięcie zamienia
tekst na pole formularza (`hx-get`), zapis wraca gotowym fragmentem (`hx-put`).
Bez przeładowania strony i bez linijki własnego JavaScriptu.

Dwie rzeczy warte zapamiętania:

- **Ręczna edycja normalizuje tak samo jak import.** Wpisane `SOBÓTKA` zapisze
  się jako `Sobótka`. Bez tego ręczne wpisy rozjechałyby się z zaimportowanymi
  i zrobiły dwa miasta w filtrze.
- **Błędna wartość nie czyści pola.** Zły adres e-mail albo kod pocztowy
  zostaje odrzucony z komunikatem, a poprzednia wartość zostaje nietknięta.
  Wyjątkiem jest NIP: cyfry zapisujemy, ale oznaczamy czerwonym `!`, bo
  wartość do przejrzenia jest cenniejsza niż puste pole.

Każda zmiana — pola, telefonu, tagu, statusu, zgody SMS — trafia na oś czasu
klienta jako `Activity`. To wymóg funkcjonalny, nie log techniczny: historia
kontaktu ma być w jednym miejscu.

Usunięcie klienta wymaga przepisania jego nazwy. Kasuje też notatki, telefony
i całą oś czasu.

---

## Rozmowy

Transkrypcje rozmów telefonicznych wrzuca do systemu osoba z zewnątrz —
endpointem, nie przez interfejs.

```
POST /api/ingest/transcript
Authorization: Bearer <INGEST_TOKEN>
```

Dwa warianty żądania:

```bash
# plik .txt (multipart)
curl -X POST https://.../api/ingest/transcript -H "Authorization: Bearer $INGEST_TOKEN" -F "file=@rozmowa.txt" -F "phone=601 092 947" -F "date=14.03.2026"

# JSON
curl -X POST https://.../api/ingest/transcript -H "Authorization: Bearer $INGEST_TOKEN" -H "Content-Type: application/json" -d '{"text": "...", "phone": "601092947", "date": "2026-03-14"}'
```

Odpowiedź przychodzi **natychmiast** (`202`), z numerem rozmowy i informacją,
co się z nią stało — nadawca nie czeka na przetwarzanie.

Do ręcznego sprawdzenia jest skrypt — bierze token z `.env`, więc nie trzeba go
nigdzie wklejać:

```powershell
.venv\Scripts\python.exe scripts\send_transcript.py --tekst "Dzień dobry, tu Kowalski, mój numer to 601 092 947."
.venv\Scripts\python.exe scripts\send_transcript.py rozmowa.txt --telefon "601 092 947" --data 14.03.2026
```

W PowerShellu `curl` jest aliasem `Invoke-WebRequest` o innej składni — stąd
skrypt zamiast gotowca z `curl`.

Co warto wiedzieć:

- **Token porównujemy `hmac.compare_digest`**, nie znakiem `==`. Zwykłe
  porównanie kończy się na pierwszym różnym znaku i przy odpowiednio wielu
  próbach zdradza token po czasie odpowiedzi. Pusty `INGEST_TOKEN` w konfiguracji
  oznacza „endpoint wyłączony" (`503`), nigdy „wpuszczaj wszystkich".
- **Kodowanie wykrywamy sami.** Pliki `.txt` z Windowsa bywają w CP1250,
  a bywają w UTF-8. Bez wykrycia polskie znaki zamieniłyby się w krzaki.
- **Limit 1 MB** na treść, większe odrzucamy czytelnym komunikatem w JSON-ie.
- Data przyjmowana po polsku (`14.03.2026`) i po ISO (`2026-03-14`).

### Dopasowanie do klienta

Numer bierzemy z pola `phone`, a gdy go nie ma — **wyłuskujemy z treści
rozmowy**. Wzorzec jest celowo ostrożny: kandydat przechodzi przez ten sam
normalizator, co import, więc NIP (`617-101-01-49`), data (`2026-03-14`)
i kwota (`1 200 000`) odpadają same, bo nie są poprawnymi numerami polskimi.

| Sytuacja | Co się dzieje |
|---|---|
| numer należy do jednego klienta | rozmowa przypięta, wpis na osi czasu |
| numeru nie ma w bazie | **zakładamy klienta** (`source=TRANSCRIPT`, tag `nowy-z-rozmowy`) |
| numer mają dwa gospodarstwa | `NEEDS_REVIEW` — system **nie zgaduje** |
| brak numeru w ogóle | `NEEDS_REVIEW`, do ręcznego przypisania |

Trzeci wiersz nie jest teoretyczny: w bazie źródłowej 58 numerów należy do
dwóch lub trzech odrębnych gospodarstw (rodzina pod jednym telefonem), dlatego
kolumna `phones.e164` celowo nie ma ograniczenia UNIQUE.

**Surowy tekst rozmowy zostaje w bazie zawsze** — także wtedy, gdy nie ma do
kogo go przypiąć.

### Ekran `/transcripts`

Lista z zakładkami; „Wymagają uwagi" łączy `NEEDS_REVIEW` i `FAILED`, bo dla
użytkownika znaczą to samo. Wyszukiwarka obejmuje treść rozmowy, nazwę klienta,
nazwę pliku i numer telefonu w dowolnym zapisie.

W panelu rozmowy przypisujesz klienta ręcznie — z listy gospodarstw mających
ten numer albo z wyszukiwarki. Przycisk „przetwórz ponownie" powtarza
dopasowanie; przydaje się, gdy numer dopisano klientowi już po rozmowie.
Zmiana przypisania zostawia ślad na osi czasu poprzedniego klienta.

Na osi czasu klienta rozmowa stoi jako jeden wpis; pełny zapis dociąga HTMX
dopiero po kliknięciu — transkrypcja potrafi mieć kilkanaście tysięcy znaków.

---

## Analiza rozmów

Każda rozmowa z przypisanym klientem trafia do modelu (DeepSeek przez SDK
`openai`), który zwraca podsumowanie, wydźwięk, wynik rozmowy, kluczowe
ustalenia i terminy do kalendarza. Wymaga `DEEPSEEK_API_KEY` w `.env` — bez
klucza aplikacja działa normalnie, tylko analiza się nie odpala i mówi o tym
raz w logu, zamiast zasypywać go co pół minuty.

Rzeczy, które warto znać, zanim się to zmieni:

- **Prompt zawiera dzisiejszą datę wraz z dniem tygodnia.** W rozmowach padają
  określenia względne („w przyszły wtorek", „za dwa tygodnie"). Bez daty
  odniesienia model wygeneruje terminy z sufitu, a te wylądują w kalendarzu.
  Datę bierzemy z czasu polskiego, nie z UTC — o pierwszej w nocy różnią się
  o dobę.
- **Odpowiedź jest walidowana Pydantikiem, z tolerancją.** Model bywa uprzejmy
  i odpowiada „pozytywny" zamiast `positive`, wstawia `"null"` jako napis albo
  datę z kropkami. Wszystko to sprowadzamy do dozwolonych wartości. Odpowiedź
  bez podsumowania albo nie-JSON to błąd i ponowna próba.
- **Wydarzenia z AI nigdy nie są potwierdzone.** Powstają z `confirmed=False`,
  przerywaną obwódką w interfejsie i pewnością `high` / `medium` / `low`.
  Niską pewność odnotowujemy dodatkowo w opisie.
- **Ustalenie bez daty nie trafia do kalendarza.** Zostaje w `ai_raw` i widać
  je na ekranie rozmowy pod nagłówkiem „Bez ustalonego terminu". Wpisanie
  wymyślonej daty byłoby gorsze niż brak wpisu.
- **Nazwę klienta model może uzupełnić tylko wtedy, gdy jest tymczasowa.**
  Klientowi założonemu z rozmowy („Nieznany (601 092 947)") nadaje nazwę
  usłyszaną w rozmowie. Nazwy z arkusza ani wpisanej ręcznie nie tknie.
- **Podsumowanie dopisujemy do istniejącego wpisu na osi czasu**, zamiast
  dokładać drugi. Jedna rozmowa to jedna pozycja w historii kontaktu.

### Kolejka i ponawianie

Zadanie APSchedulera chodzi co 30 sekund i bierze porcję rozmów
(`SELECT ... FOR UPDATE SKIP LOCKED`, `max_instances=1`). Nieudana próba zwiększa
licznik i odsuwa kolejną o rosnący odstęp — 1, 5 i 15 minut. Po trzeciej rozmowa
dostaje status `FAILED` i czeka na przycisk „Przetwórz ponownie”.

**Surowy tekst rozmowy zostaje w bazie zawsze**, także po nieudanej analizie.

Rozmowa, która utknie w stanie „Przetwarzanie" (na przykład przez ubicie procesu
w trakcie odpytywania modelu), wraca do kolejki po kwadransie.

Ponowne przetworzenie kasuje wydarzenia **niepotwierdzone**; te, które
potwierdziłeś, zostają — są już Twoją decyzją, nie modelu.

Panel rozmowy dopytuje o wynik przez HTMX co trzy sekundy, a gdy analiza jest
gotowa, fragment wraca bez wyzwalacza i odpytywanie samo się kończy.

Zużycie tokenów zapisujemy przy każdej rozmowie; suma miesięczna trafi do
`/settings` w etapie 8 (`analysis.tokens_used_this_month()`).

---

## Kalendarz

Ekran `/calendar` — FullCalendar 6 w widokach miesiąca, tygodnia i agendy,
zasilany endpointem JSON. Kliknięcie w wydarzenie otwiera panel obok
(fragment HTML przez HTMX) z przyciskami Potwierdź / Edytuj / Usuń; kliknięcie
w pusty dzień otwiera formularz nowego wpisu z tą datą.

**Trzy stany wydarzenia, trzy wyglądy** — wszystkie w palecie marki:

| Wygląd | Znaczenie |
|---|---|
| przerywana obwódka `amber-600` na tle `amber-50` | propozycja z rozmowy, niepotwierdzona |
| pełne tło `amber-500`, czarny tekst | potwierdzony termin z rozmowy |
| tło `ink-900`, biały tekst | wpis zrobiony ręcznie |

Rzeczy warte zapamiętania:

- **Wydarzenie z AI to propozycja, nie fakt.** Potwierdzenie jest jedynym
  sposobem, w jaki termin z modelu staje się ustaleniem. Poprawienie go ręcznie
  też liczy się jako potwierdzenie — użytkownik właśnie wpisał własną wartość,
  więc udawanie, że decyzji nie było, byłoby nieuczciwe.
- **Czas polski na wejściu i wyjściu, UTC w bazie.** Kalendarz dostaje daty
  z jawnym przesunięciem (`2026-09-01T14:00:00+02:00`), więc niczego nie zgaduje,
  a przejście na czas zimowy nie przesuwa terminów. Testy pilnują obu przesunięć.
- **Pusta godzina znaczy „cały dzień".** Większość ustaleń z rozmów brzmi
  „przyjadę w czwartek", więc wymuszanie godziny kazałoby ją zmyślać.
- **Usunięcie pyta o potwierdzenie** fragmentem z serwera, nie okienkiem
  `confirm()`, a ślad zostaje na osi czasu klienta.
- Panel wydarzenia pokazuje **fragment rozmowy, z której termin powstał** —
  kontekst pod ręką, bez szukania po ekranie rozmów.

**Odstępstwo od specyfikacji:** FullCalendar leży w `static/js`, nie jest
ciągnięty z CDN. Powód jest ten sam, dla którego font Inter hostujemy lokalnie,
a HTMX i Alpine leżą w repozytorium: sieć, w której instalacja z PyPI zrywała
połączenie, potrafi zablokować także CDN — a kalendarz bez biblioteki to pusty
prostokąt. Plik waży 282 kB i ładuje się **tylko na tym jednym ekranie**.
Powrót na CDN to podmiana jednej linii w `calendar/index.html`.

---

## Testy

```powershell
.venv\Scripts\python.exe -m pytest              # wszystko
.venv\Scripts\python.exe -m pytest -m "not db"  # bez bazy danych
```

Testami objęte są miejsca, w których błąd po cichu zepsułby 2000 rekordów albo
kosztowałby realne pieniądze: normalizacja telefonów, NIP-ów, miast i kodów
pocztowych, mapowanie kolumn i deduplikacja w importerze, wyszukiwanie po
numerze, wyłuskiwanie numeru z treści rozmowy, autoryzacja endpointu
transkrypcji oraz parsowanie odpowiedzi modelu wraz z przeliczaniem terminów
na UTC. Przypadki testowe pochodzą z prawdziwego pliku.

Testy AI **nie ruszają sieci** — dostawca modelu jest podstawiany, więc nic
nie kosztują i działają bez klucza API.

Jakość kodu:

```powershell
.venv\Scripts\python.exe -m ruff format .
.venv\Scripts\python.exe -m ruff check .
.venv\Scripts\python.exe -m mypy app
```

---

## Wygląd

Marka jest **dwukolorowa**: bursztyn `#FFAF00` i czerń. Paleta w
[`tailwind.config.js`](tailwind.config.js).

Reguła kontrastu, której trzymamy się bezwzględnie:

| Zestawienie | Kontrast | Werdykt |
|---|---|---|
| `amber-500` na białym | 1.84:1 | ❌ nigdy jako kolor tekstu |
| biały tekst na bursztynie | 1.84:1 | ❌ nigdy |
| **czarny tekst na bursztynie** | 11.4:1 | ✅ przyciski główne |
| `amber-800` na białym | 5.54:1 | ✅ linki i etykiety |

Warianty logo generuje skrypt:

```powershell
python scripts\make_logo_assets.py
```

Powstają `logo.png` (na jasne tło), `logo-light.png` (na sidebar `ink-950`)
i favicon z kadrem na traktor. Wariant jasny jest konieczny: pod napisem
„NOXSO" tło jest przezroczyste, więc czarne litery na ciemnym sidebarze
zniknęłyby całkowicie.

---

## Zadania w tle

APScheduler chodzi w procesie aplikacji. Import 2000 wierszy nie zmieściłby się
w limicie czasu żądania HTTP, więc widok tylko zakłada zadanie, a postęp
pokazywany jest przez HTMX (odpytywanie co 2 s).

`Procfile` uruchamia Gunicorna z **jednym** workerem — to celowe, przy większej
liczbie procesów to samo zadanie wykonałoby się kilka razy.

---

## Deploy na Railway

> **Plik `.env` NIE jedzie na serwer.** Jest w `.gitignore` i tak ma zostać.
> Wszystkie zmienne wpisujesz w panelu Railwaya, ręcznie.

### Zanim klikniesz cokolwiek

Aplikacja stanie pod publicznym adresem, więc **hasło z developmentu przestaje
wystarczać**. Wygeneruj nowe, mocne, i osobny komplet sekretów:

```powershell
.venv\Scripts\python.exe scripts\hash_password.py                       # ADMIN_PASSWORD_HASH
.venv\Scripts\python.exe -c "import secrets; print(secrets.token_hex(32))"      # SECRET_KEY
.venv\Scripts\python.exe -c "import secrets; print(secrets.token_urlsafe(32))"  # INGEST_TOKEN
```

Produkcyjny `SECRET_KEY` ma być **inny** niż lokalny — wyciek jednego nie może
otwierać drugiego. `INGEST_TOKEN` też generujesz nowy, bo dopiero teraz stanie
się realnie osiągalny z internetu.

### Kroki

1. **Nowy projekt** → *Deploy from GitHub repo* → `pkrodev/crmnoxso`.
2. **Dodaj usługę PostgreSQL** w tym samym projekcie (*New* → *Database* →
   *Add PostgreSQL*).
3. **Zmienne środowiskowe** w usłudze aplikacji (*Variables*):

   | Zmienna | Wartość |
   |---|---|
   | `DATABASE_URL` | `${{Postgres.DATABASE_URL}}` — odwołanie do usługi bazy, nie wklejony adres |
   | `FLASK_ENV` | `production` |
   | `FLASK_APP` | `wsgi.py` |
   | `TZ` | `Europe/Warsaw` |
   | `SECRET_KEY` | świeżo wygenerowany |
   | `ADMIN_LOGIN` | `Milosz` |
   | `ADMIN_PASSWORD_HASH` | hash **mocnego** hasła |
   | `INGEST_TOKEN` | świeżo wygenerowany |
   | `DEEPSEEK_API_KEY` | klucz z platform.deepseek.com |
   | `AI_MODEL` | `deepseek-chat` |
   | `SCHEDULER_ENABLED` | `1` |

   SMS-owe (`SMSPLANET_TOKEN`, `SMSPLANET_SIGNATURE_KEY`, `SMS_SENDER_NAME`)
   dołożysz przy etapie 7 — bez nich aplikacja działa, tylko kampanie nie ruszą.

4. **Wygeneruj domenę**: *Settings* → *Networking* → *Generate Domain*.
5. **Healthcheck** (opcjonalnie, ale warto): *Settings* → *Deploy* →
   *Healthcheck Path* → `/api/healthz`.

Migracje odpalają się **w komendzie startowej**, przed Gunicornem, więc pierwszy
deploy zakłada cały schemat sam.

> Railway czyta z `Procfile` wyłącznie linię `web:` i kroku `release:` **nie
> wykonuje**. Sprawdzone na żywym wdrożeniu: aplikacja wstała, `/api/healthz`
> odpowiadał `database:true` (bo to gołe `select 1`), a pierwsze prawdziwe
> żądanie trafiło w nieistniejący schemat. Dlatego `flask db upgrade` jest
> częścią komendy startowej — jest idempotentne, a worker jest jeden.

### Po wdrożeniu

```powershell
# czy żyje i co ma skonfigurowane
curl.exe https://TWOJA-DOMENA.up.railway.app/api/healthz

# rozmowa na produkcję
.venv\Scripts\python.exe scripts\send_transcript.py --adres https://TWOJA-DOMENA.up.railway.app --token PRODUKCYJNY_INGEST_TOKEN --tekst "Rozmowa testowa, numer 601 092 947."
```

`/api/healthz` zwraca `{"status":"ok","database":true,"ingest":true,"ai":true}`.
Zawsze odpowiada 200, dopóki proces żyje — stan bazy jest w treści, nie w kodzie
odpowiedzi, bo restart aplikacji i tak nie naprawi leżącego Postgresa.

Bazę klientów wgrywasz przez `/import` tak samo jak lokalnie. Plik `.xlsx`
zostaje na Twoim dysku i nigdy nie trafia do repozytorium.

### Rzeczy, o których warto wiedzieć

- **Jeden worker jest obowiązkowy.** `Procfile` uruchamia Gunicorna z
  `--workers 1`, bo APScheduler chodzi w procesie aplikacji. Przy dwóch
  workerach każda rozmowa poszłaby do modelu dwa razy — i tyle samo kosztowała.
- **Dysk jest ulotny.** Arkusz wgrany na `/import` żyje do najbliższego
  wdrożenia. Import startuje od razu po potwierdzeniu, więc w praktyce to nie
  przeszkadza, ale nie zostawiaj wgranego pliku „na później".
- **Python 3.13** — wersję przypina plik `.python-version`. Bez niego platforma
  wybrałaby własną domyślną, a wersje paczek w `requirements.txt` są dobrane
  pod 3.13.
- **Styli nie trzeba budować.** `tailwind.css` jest w repozytorium właśnie po to
  — Railway nie ma Node'a. Po każdej zmianie w szablonach przebuduj go lokalnie
  i zacommituj, inaczej produkcja pojedzie ze starym arkuszem.
- **Ciasteczka sesji mają flagę `Secure`** w konfiguracji produkcyjnej, więc
  logowanie zadziała wyłącznie po HTTPS — na Railwayu to domyślne.

Opcjonalnie: SMSPlanet pozwala ograniczyć dostęp do API listą adresów IP.
Railway daje stabilniejsze adresy wyjściowe niż platformy bezserwerowe, ale
**nie gwarantuje statycznego IP** — nie włączaj tej filtracji domyślnie.

---

## Struktura

```
app/
├── __init__.py          fabryka aplikacji
├── config.py            konfiguracja z ENV
├── extensions.py        db, login_manager, scheduler, csrf, limiter
├── auth_user.py         jedyny użytkownik (bez tabeli w bazie)
├── filters.py           filtry Jinja (daty w Europe/Warsaw, telefony, NIP)
├── tasks.py             zadania APSchedulera
├── models/              modele SQLAlchemy 2.0
├── blueprints/          auth, dashboard, clients, imports, transcripts,
│                        calendar, api
├── services/
│   ├── normalize.py     telefony, NIP, miasta, kody pocztowe
│   ├── importer.py      odczyt arkusza, deduplikacja, zapis
│   ├── clients.py       wyszukiwanie, filtry, edycja pól, oś czasu
│   ├── matching.py      numer z treści rozmowy → klient
│   ├── transcripts.py   lista rozmów, zakładki, liczniki
│   ├── ai.py            prompt, dostawca modelu, walidacja odpowiedzi
│   ├── analysis.py      kolejka analizy, wydarzenia, ponawianie
│   ├── calendar.py      wydarzenia, strefy czasowe, potwierdzanie
│   └── paging.py        stronicowanie wspólne dla list
├── templates/
└── static/
scripts/                 hash hasła, warianty logo, build CSS, kontrola normalizacji,
                         wysyłka testowej transkrypcji
tests/                   pytest
wheels/                  paczki pobrane ręcznie (obejście blokady PyPI)
```
