# Paczki do pobrania ręcznie

Sieć, w której stoi ten komputer, blokuje pobieranie paczek z PyPI — serwer odpowiada
`200 OK`, po czym połączenie jest zrywane przed pierwszym bajtem treści. Dotyczy to zarówno
`pip`, jak i `curl`, więc obejścia po stronie narzędzi nie ma.

W tym katalogu jest wszystko, czego potrzeba, żeby pobrać paczki gdzie indziej i wgrać je tutaj.

| Plik | Do czego |
|---|---|
| `lista-url.txt` | 75 adresów, jeden na linię — do menedżera pobierania albo skryptu |
| `lista.json` | to samo z nazwami plików i rozmiarami |
| `pobierz.ps1` | pobiera wszystko automatycznie |

**Razem: 75 plików, 62 MB.** Lista jest kompletna — rozwiązałem całe drzewo zależności
(z metadanymi PyPI, bo te akurat przechodzą), łącznie z zależnościami zależności.
Wersje pasują dokładnie do Pythona 3.13 na Windows x64.

---

## Wariant 1 — hotspot z telefonu (najszybszy)

1. Włącz udostępnianie internetu w telefonie, podepnij laptopa do tej sieci.
2. W katalogu projektu:

   ```powershell
   powershell -ExecutionPolicy Bypass -File wheels\pobierz.ps1
   ```

3. Skrypt pokazuje postęp plik po pliku. Przerwane pobieranie? Uruchom ponownie —
   pominie to, co już jest.
4. Wróć do sieci firmowej. Instalacja jest już offline:

   ```powershell
   .venv\Scripts\python.exe -m pip install --no-index --find-links wheels -r requirements-dev.txt
   ```

## Wariant 2 — inny komputer

Skopiuj `pobierz.ps1` i `lista-url.txt` na pendrive, uruchom skrypt na komputerze z dostępem,
przenieś pobrane pliki z powrotem do katalogu `wheels/`. Potem polecenie `pip install` jak wyżej.

Jeśli na tamtym komputerze jest Python 3.13, wystarczy równoważnie:

```powershell
pip download -r requirements-dev.txt -d wheels --only-binary=:all: --platform win_amd64 --python-version 313
```

## Wariant 3 — przeglądarka

Otwórz `lista-url.txt`, pobieraj kolejne adresy przez przeglądarkę. 75 kliknięć —
sensowne tylko wtedy, gdy przeglądarka chodzi innym kanałem niż reszta systemu
(sprawdź jednym adresem, zanim zaczniesz).

Wszystkie pliki muszą wylądować **bezpośrednio w katalogu `wheels/`**, bez podkatalogów
i bez zmiany nazw — `pip` rozpoznaje paczki po nazwie pliku.

---

## Osobno: PostgreSQL 16

Nie ma go w tej liście, to zwykły instalator Windows:

<https://www.enterprisedb.com/downloads/postgres-postgresql-downloads> → **PostgreSQL 16.x, Windows x86-64**

Podczas instalacji:

- hasło użytkownika `postgres` — zapamiętaj, wpiszemy je do `.env`,
- port `5432` (domyślny),
- locale: `Polish, Poland` albo `C` — bez znaczenia dla aplikacji,
- Stack Builder na końcu: **pomiń**, nic stamtąd nie jest potrzebne.

Bazę `noxso_crm` założę sam skryptem `scripts/create_db.sql`, gdy PostgreSQL będzie działał.

---

## Co potem

Daj znać, że pliki są. Sprawdzę komplet, zainstaluję offline, uruchomię migracje i testy.
Cały kod aplikacji powstaje niezależnie od tego — instalacja jest potrzebna dopiero
do **uruchomienia** i weryfikacji.
