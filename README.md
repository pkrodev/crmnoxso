# NOXSO CRM

Jednoosobowy CRM dla firmy NOXSO (branża rolnicza, Wielkopolska).
Specyfikacja projektu: [`CLAUDE.md`](CLAUDE.md).

Stan prac: **etapy 1–4** (fundament, import z normalizacją, ekran klientów,
transkrypcje rozmów), uruchomione i sprawdzone na prawdziwej bazie
1923 kontrahentów. Etapy 5–8 — AI, kalendarz, SMS, ustawienia — przed nami.

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
# plik .txt
curl -X POST https://.../api/ingest/transcript      -H "Authorization: Bearer $INGEST_TOKEN"      -F "file=@rozmowa.txt" -F "phone=601 092 947" -F "date=14.03.2026"

# JSON
curl -X POST https://.../api/ingest/transcript      -H "Authorization: Bearer $INGEST_TOKEN"      -H "Content-Type: application/json"      -d '{"text": "...", "phone": "601092947", "date": "2026-03-14"}'
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

## Testy

```powershell
.venv\Scripts\python.exe -m pytest              # wszystko
.venv\Scripts\python.exe -m pytest -m "not db"  # bez bazy danych
```

Testami objęte są miejsca, w których błąd po cichu zepsułby 2000 rekordów:
normalizacja telefonów, NIP-ów, miast i kodów pocztowych, mapowanie kolumn
i deduplikacja w importerze, wyszukiwanie po numerze oraz wyłuskiwanie numeru
z treści rozmowy i autoryzacja endpointu transkrypcji. Przypadki testowe
pochodzą z prawdziwego pliku.

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

1. Nowy projekt → *Deploy from GitHub repo*.
2. Dodaj usługę **PostgreSQL** w tym samym projekcie.
3. Zmienne środowiskowe: jak w `.env.example`. `DATABASE_URL` Railway wstawi sam
   (aplikacja podmienia prefiks `postgres://` na `postgresql+psycopg://`).
4. Migracje odpalają się przy każdym wdrożeniu — komenda `release` z `Procfile`.
5. Style: `tailwind.css` jest w repozytorium, więc build nie wymaga Node'a.

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
├── blueprints/          auth, dashboard, clients, imports, transcripts, api
├── services/
│   ├── normalize.py     telefony, NIP, miasta, kody pocztowe
│   ├── importer.py      odczyt arkusza, deduplikacja, zapis
│   ├── clients.py       wyszukiwanie, filtry, edycja pól, oś czasu
│   ├── matching.py      numer z treści rozmowy → klient
│   ├── transcripts.py   lista rozmów, zakładki, liczniki
│   └── paging.py        stronicowanie wspólne dla list
├── templates/
└── static/
scripts/                 hash hasła, warianty logo, build CSS, kontrola normalizacji,
                         wysyłka testowej transkrypcji
tests/                   pytest
wheels/                  paczki pobrane ręcznie (obejście blokady PyPI)
```
