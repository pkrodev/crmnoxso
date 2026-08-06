# NOXSO CRM

Jednoosobowy CRM dla firmy NOXSO (branża rolnicza, Wielkopolska).
Specyfikacja projektu: [`CLAUDE.md`](CLAUDE.md).

Stan prac: **etapy 1–2** (fundament + import z normalizacją). Etapy 3–8 —
klienci, transkrypcje, AI, kalendarz, SMS, ustawienia — dopiero przed nami.

---

## Uruchomienie od zera

### 1. PostgreSQL 16

Instalator: <https://www.enterprisedb.com/downloads/postgres-postgresql-downloads>
→ *PostgreSQL 16.x, Windows x86-64*. Podczas instalacji zapamiętaj hasło
użytkownika `postgres`, port zostaw `5432`, Stack Buildera na końcu pomiń.

Bazy zakładasz raz:

```powershell
& "C:\Program Files\PostgreSQL\16\bin\psql.exe" -U postgres -f scripts\create_db.sql
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

### 4. Baza i style

```powershell
$env:FLASK_APP = "wsgi.py"
.venv\Scripts\flask.exe db upgrade
.\scripts\build_css.ps1
```

### 5. Start

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

## Testy

```powershell
.venv\Scripts\python.exe -m pytest              # wszystko
.venv\Scripts\python.exe -m pytest -m "not db"  # bez bazy danych
```

Testami objęte są miejsca, w których błąd po cichu zepsułby 2000 rekordów:
normalizacja telefonów, NIP-ów, miast i kodów pocztowych oraz mapowanie kolumn
i deduplikacja w importerze. Przypadki testowe pochodzą z prawdziwego pliku.

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
├── blueprints/          auth, dashboard, imports
├── services/
│   ├── normalize.py     telefony, NIP, miasta, kody pocztowe
│   └── importer.py      odczyt arkusza, deduplikacja, zapis
├── templates/
└── static/
scripts/                 hash hasła, warianty logo, build CSS, kontrola normalizacji
tests/                   pytest
wheels/                  paczki pobrane ręcznie (obejście blokady PyPI)
```
