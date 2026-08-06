# NOXSO CRM — specyfikacja projektu

Dokument dla Claude Code. Buduj zgodnie z tym opisem, etapami z sekcji
[Kolejność prac](#11-kolejność-prac). Po każdym etapie zatrzymaj się i pokaż efekt
do akceptacji.

---

## 1. Czym to jest

Jednoosobowy CRM dla firmy NOXSO, działającej w branży rolniczej (klienci: gospodarstwa
rolne, spółdzielnie kółek rolniczych, firmy rolnicze z Wielkopolski).

**Kluczowe założenia, które zmieniają decyzje architektoniczne:**

- **Klienci NIGDY się nie logują.** Nie ma portalu klienta, rejestracji ani resetu hasła
  dla klienta. Jest dokładnie jeden użytkownik systemu — właściciel. Nie buduj systemu
  ról, uprawnień, multi-tenancy ani zaproszeń.
- **Skala jest mała:** ~2000 kontaktów, kilkanaście–kilkadziesiąt transkrypcji dziennie.
  Nie optymalizuj przedwcześnie. Nie potrzeba Redisa, Celery, Dockera w developmencie
  ani mikroserwisów.
- **Dane są brudne.** Baza wejściowa to eksport z systemu księgowego z niespójnymi
  formatami. Normalizacja jest funkcją krytyczną, nie dodatkiem — patrz sekcja 5.
- **Właściciel zna Pythona, nie zna JavaScriptu.** To determinuje stack i sposób
  budowy interfejsu: minimum JS, maksimum logiki po stronie serwera. Gdy stajesz przed
  wyborem „reaktywny komponent JS" kontra „fragment HTML z serwera przez HTMX" —
  wybieraj to drugie.
- Interfejs po polsku. Nazwy w kodzie (zmienne, tabele, funkcje) po angielsku.

---

## 2. Stack

| Warstwa | Wybór | Uzasadnienie |
|---|---|---|
| Język | Python 3.12 | |
| Framework | Flask 3.x (blueprints, app factory) | znany właścicielowi |
| Szablony | Jinja2 | |
| Interaktywność | HTMX 2.x + Alpine.js (tylko tam, gdzie konieczne) | bez budowania frontendu |
| CSS | Tailwind CSS — **standalone CLI**, bez Node/npm | patrz niżej |
| Baza | PostgreSQL 16 | |
| ORM | SQLAlchemy 2.0 (styl deklaratywny, `Mapped[]`) | |
| Migracje | Alembic | |
| Walidacja | Pydantic v2 | każde wejście: formularze, API, odpowiedzi AI |
| Auth | Flask-Login, jeden użytkownik z ENV | patrz sekcja 7 |
| Formularze | Flask-WTF (ochrona CSRF) | |
| Zadania w tle | APScheduler w procesie aplikacji | patrz sekcja 9 |
| HTTP | `httpx` | |
| Arkusze | `pandas` + `odfpy` (czyta `.ods`) | |
| Telefony | `phonenumbers` | |
| NIP | `python-stdnum` (`stdnum.pl.nip`) | gotowa walidacja sumy kontrolnej |
| AI | DeepSeek przez SDK `openai` | patrz sekcja 9 |
| SMS | SMSPlanet.pl przez własny adapter | patrz sekcja 8 |
| Kalendarz | FullCalendar 6 z CDN | |
| Serwer | Gunicorn | |
| Hosting | **Railway** | patrz niżej |
| Testy | pytest | zakres w sekcji 12 |

**Dlaczego Railway, a nie Vercel:** Flask na Vercelu działa jako funkcja bezstanowa,
co odbiera największą zaletę tego stacku — stały proces, w którym APScheduler może
przetwarzać transkrypcje w tle. Na Railwayu masz zwykły proces WSGI i bazę Postgres
w tym samym projekcie.

**Tailwind bez Node:** pobierz standalone binarkę Tailwind CLI (jeden plik wykonywalny,
zero zależności npm). Wywołanie w trybie watch podczas developmentu, jednorazowy build
przy deployu. Właściciel nie ma i nie potrzebuje mieć Node'a na maszynie.

**Nie dodawaj:** Celery, Redisa, Dockera w developmencie, Django, osobnego frontendu
w React/Vue, GraphQL. Jeśli uważasz, że coś z tego jest naprawdę potrzebne — zapytaj,
zanim dodasz.

### Struktura katalogów

```
noxso-crm/
├── app/
│   ├── __init__.py          # app factory
│   ├── config.py            # konfiguracja z ENV
│   ├── extensions.py        # db, login_manager, scheduler, csrf
│   ├── models/              # modele SQLAlchemy
│   ├── blueprints/
│   │   ├── auth.py
│   │   ├── clients.py
│   │   ├── campaigns.py
│   │   ├── calendar.py
│   │   ├── transcripts.py
│   │   ├── imports.py
│   │   ├── settings.py
│   │   └── api.py           # endpoint ingest + webhook SMS
│   ├── services/
│   │   ├── normalize.py     # telefony, NIP, miasta, kody pocztowe
│   │   ├── importer.py
│   │   ├── sms/
│   │   │   ├── base.py      # interfejs SmsProvider
│   │   │   └── smsplanet.py
│   │   ├── ai.py
│   │   └── matching.py      # dopasowanie transkrypcji do klienta
│   ├── templates/
│   ├── static/
│   └── tasks.py             # zadania APScheduler
├── migrations/              # Alembic
├── tests/
├── scripts/
├── requirements.txt
├── .env.example
└── wsgi.py
```

---

## 3. Identyfikacja wizualna

Marka: **NOXSO**. Logo (`app/static/img/logo.png`, 681×380, PNG z przezroczystością) —
sylwetka traktora na tle promieni słonecznych plus typografia „NOXSO".

**Paleta wyciągnięta z pliku — dokładnie dwa kolory:**

| Kolor | HEX | Udział w logo |
|---|---|---|
| Bursztyn | `#FFAF00` | 30% |
| Czerń | `#000000` | 25% |
| Przezroczystość / biel | — | 39% |

To marka dwukolorowa. Nie dodawaj trzeciego koloru brandowego — kolory poza tą paletą
rezerwuj wyłącznie dla stanów semantycznych.

### Skala odcieni

Wpisz do `tailwind.config.js` (plik konfiguracyjny działa też ze standalone CLI):

```js
theme: {
  extend: {
    colors: {
      amber: {
        50:'#FAF2E1', 100:'#F5E4BF', 200:'#F0D395', 300:'#EDC46B',
        400:'#F2B93D', 500:'#FFAF00', 600:'#DB9600', 700:'#B27A00',
        800:'#8C6000', 900:'#6B4A00', 950:'#473100',
      },
      ink: {
        50:'#FAFAFA', 200:'#E5E5E5', 500:'#737373',
        700:'#404040', 900:'#171717', 950:'#0A0A0A',
      },
    },
  },
}
```

### Reguła kontrastu — **przestrzegaj jej bezwzględnie**

`#FFAF00` na białym tle daje kontrast **1.84:1**. To poniżej progu WCAG AA (4.5:1) —
tekst w tym kolorze na jasnym tle jest nieczytelny. Zweryfikowane, nie szacowane.

- ❌ **Nigdy** `amber-500` jako kolor tekstu na jasnym tle.
- ❌ Nigdy białego tekstu na bursztynowym tle (1.84:1).
- ✅ **Czarny tekst na bursztynie** — 11.4:1. Tak robisz przyciski główne:
  tło `amber-500`, tekst `ink-950`.
- ✅ Tekst bursztynowy na białym dopiero od `amber-800` (`#8C6000`, 5.54:1) — linki, etykiety.
- ✅ Bursztyn na ciemnym tle sidebara — świetny kontrast, używaj swobodnie.

### Zastosowanie

- **Sidebar:** tło `ink-950`, logo na górze. Sprawdź, czy czarny napis „NOXSO" nie znika
  na czerni; jeśli tak, potrzebny wariant z białym napisem i zachowanym bursztynem.
- **Aktywna pozycja nawigacji:** pasek 3px `amber-500` po lewej + tekst `amber-500`.
- **Przycisk główny:** tło `amber-500`, tekst czarny, hover `amber-600`.
- **Przycisk drugorzędny:** obramowanie `ink-200`, tekst `ink-900`.
- **Obszar treści:** tło `ink-50`, karty białe z obramowaniem `ink-200`, bez cieni.
- **Nagłówki tabel:** tło `amber-50`, tekst `ink-900`. Wiersz zaznaczony: `amber-100`.
- **Wydarzenia AI w kalendarzu:** przerywana obwódka `amber-600` na tle `amber-50`
  (potwierdzone: tło `amber-500`, tekst czarny).

### Stany semantyczne

Bursztyn jest zbyt bliski typowej żółci ostrzegawczej — dla ostrzeżeń użyj **pomarańczy**
(`#EA580C`), nie żółci, inaczej ostrzeżenie zleje się z brandem.
Sukces: `#15803D`. Błąd: `#B91C1C`.

### Pozostałe zasady wizualne

- Gęsty, „narzędziowy" interfejs — aplikacja do pracy, nie landing page. Tabele mają
  mieścić dużo wierszy bez scrollowania.
- Bez gradientów, mocnych cieni i animacji wejścia.
- Font: **Inter hostowany lokalnie** w `static/fonts` (bez zewnętrznego CDN).
  Musi obsługiwać `ąćęłńóśźż` w każdej użytej wadze.
- Nagłówki sekcji wersalikami z rozstrzelonymi literami — nawiązanie do logo.
- Nazwa klienta zawsze jako najbardziej wyeksponowany element wiersza.
- Logo w sidebarze i na ekranie logowania. Favicon: kadr na sam traktor (pełne logo
  jest za szerokie, żeby czytać się w 32×32).

---

## 4. Model danych (SQLAlchemy 2.0)

Poniżej struktura logiczna. Zapisz jako modele deklaratywne z `Mapped[]`
i `mapped_column()`, w osobnych plikach w `app/models/`.

### `Client`
| Pole | Typ | Uwagi |
|---|---|---|
| `id` | int, PK | |
| `acronym` | str, unique, nullable | `"10009"` z arkusza — **string**, wiodące zera mają znaczenie |
| `name` | str, not null | nazwa firmy / gospodarstwa |
| `nip` | str, nullable | znormalizowany, same cyfry |
| `nip_valid` | bool, default False | wynik walidacji sumą kontrolną |
| `city`, `postal_code`, `street` | str, nullable | |
| `email` | str, nullable | |
| `source` | enum: IMPORT / MANUAL / TRANSCRIPT | |
| `status` | enum: ACTIVE / INACTIVE / BLACKLIST | |
| `sms_consent` | bool, default False | patrz sekcja 8 |
| `sms_consent_at` | datetime, nullable | |
| `created_at`, `updated_at` | datetime | |

Indeksy na `name` i `city`. Relacje: `phones`, `notes`, `activities`, `transcripts`,
`events`, `tags` (many-to-many).

### `Phone`
Osobna tabela — jeden klient może mieć wiele numerów, a w arkuszu zdarzają się dwa
numery w jednej komórce.

| Pole | Typ | Uwagi |
|---|---|---|
| `id` | int, PK | |
| `client_id` | FK → Client, cascade delete | |
| `e164` | str, unique, nullable | `+48601092947` — **klucz dopasowania transkrypcji** |
| `raw` | str | oryginał z importu, do audytu |
| `is_primary` | bool | |
| `label` | str, nullable | „komórka", „biuro" |

`e164` może być `None`, gdy numeru nie da się sparsować — rekord i tak zostaje.

### `Note`
`id`, `client_id` (cascade), `body` (text, markdown), `pinned` (bool),
`created_at`, `updated_at`. Indeks złożony `(client_id, created_at)`.

### `Activity` — oś czasu klienta
To wymóg funkcjonalny, nie logowanie techniczne. Użytkownik ma widzieć historię
kontaktu z klientem w jednym miejscu.

`id`, `client_id` (cascade), `type` (enum), `title`, `description` (nullable),
`meta` (JSONB, np. `{"field":"email","from":"x","to":"y"}`), `actor` (enum),
`occurred_at`. Indeks `(client_id, occurred_at)`.

`ActivityType`: `CLIENT_CREATED`, `CLIENT_UPDATED`, `NOTE_ADDED`, `SMS_SENT`,
`SMS_DELIVERED`, `SMS_FAILED`, `CALL_TRANSCRIBED`, `EVENT_SCHEDULED`, `TAG_ADDED`,
`TAG_REMOVED`, `MANUAL`.
`ActivityActor`: `USER`, `SYSTEM`, `AI`.

### `Transcript`
`id`, `client_id` (FK, nullable), `raw_text` (text), `phone_raw`, `phone_e164`,
`call_date` (nullable), `status` (enum: `PENDING` / `PROCESSING` / `DONE` / `FAILED` /
`NEEDS_REVIEW`), `ai_summary`, `ai_sentiment`, `ai_outcome`, `ai_raw` (JSONB),
`tokens_used` (int, nullable), `error` (nullable), `source_file`, `attempts` (int,
default 0), `created_at`, `processed_at`. Indeksy na `status` i `phone_e164`.

### `CalendarEvent`
`id`, `client_id` (nullable), `transcript_id` (nullable), `title`, `description`,
`starts_at`, `ends_at` (nullable), `all_day` (bool), `source` (enum: `MANUAL` / `AI`),
`confidence` (str, nullable — z AI), `confirmed` (bool, default False), `created_at`.
Indeks na `starts_at`.

### `Campaign`
`id`, `name`, `message` (treść z placeholderami `{{name}}`, `{{city}}`),
`status` (enum: `DRAFT` / `TESTED` / `SCHEDULED` / `SENDING` / `SENT` / `PARTIAL` /
`FAILED`), `clear_polish` (bool), `scheduled_at`, `sent_at`, `tested_at`,
`test_report` (JSONB), `created_at`. Relacje: `batches`, `recipients`.

### `CampaignBatch`
Jedno żądanie do API dostawcy = jedna paczka. Kampania bez personalizacji to zwykle
jedna paczka na 2000 numerów; z personalizacją — paczki po 100.

`id`, `campaign_id` (cascade), `provider_id` (messageId od SMSPlanet, nullable),
`buffered` (bool — gdy `provider_id` zaczyna się od `B-`), `recipient_count`,
`status`, `error_code` (int, nullable), `error_message`, `sent_at`.
Indeksy na `campaign_id` i `provider_id`.

### `CampaignRecipient`
`id`, `campaign_id` (cascade), `client_id`, `phone_e164`, `rendered_text`,
`status` (`PENDING` / `SENT` / `DELIVERED` / `FAILED` / `SKIPPED`), `parts` (int,
nullable — z webhooka), `delivered_at`, `delivery_error`, `sent_at`.
Indeksy `(campaign_id, status)` i `phone_e164`.

### `Tag`
`id`, `name` (unique), `color` (nullable). Many-to-many z `Client`.

---

## 5. Import i normalizacja danych — **to jest krytyczne**

Plik wejściowy: `.ods` (LibreOffice), ~2000 wierszy, jeden arkusz `Arkusz1`.
Wiersz 1 to tytuł („Zawartość grupy kontrahentów"), **wiersz 2 to nagłówki**,
dane od wiersza 3.

```python
df = pd.read_excel(path, engine="odf", header=None, dtype=str)
# nagłówki: df.iloc[1], dane: df.iloc[2:]
```

`dtype=str` jest obowiązkowe — bez tego pandas zamieni akronim `0156` na liczbę 156,
a numer telefonu na float.

Kolumny: `Akronim | Miasto | Prefiks | Nip | Kod p. | Ulica | Opiekun | Telefon | Nazwa | E-mail`.
Kolumny `Prefiks` i `Opiekun` są praktycznie puste — zignoruj przy imporcie.

### Realne problemy w danych (zweryfikowane na próbce)

Każdy z poniższych przypadków musi być obsłużony i pokryty testem w `tests/test_normalize.py`.

**Telefony — cztery konwencje w jednej kolumnie:**
```
+48627528058          → +48627528058
607137842             → +48607137842   (9 cyfr, dodaj prefiks)
601-092-947           → +48601092947
889 869 505           → +48889869505
606420728   632767173 → DWA numery w jednej komórce → dwa rekordy Phone
```
Użyj `phonenumbers.parse(raw, "PL")` + `is_valid_number()` + format E164.
Rozdzielaj po whitespace, przecinku i średniku, potem waliduj każdy fragment osobno.
Nieparsowalny numer → zapisz w `Phone.raw`, `e164 = None`, oznacz klienta tagiem
`do-weryfikacji`. **Nie wyrzucaj rekordu.**

**NIP — trzy formaty:**
```
617-101-01-49   → 6171010149
5140006040      → 5140006040
622-00-21-912   → 6220021912   (nietypowe grupowanie, ale poprawne 10 cyfr)
(puste)         → None
```
Zdejmij wszystko poza cyframi, potem `stdnum.pl.nip.is_valid()`. Nie implementuj sumy
kontrolnej ręcznie. Wynik do `nip_valid`.

**Miasta — niespójna wielkość liter:** `DOBRZYCA`, `SOBÓTKA`, `JAROCIN` wielkimi,
reszta normalnie. „Sobótka" występuje w obu wariantach, więc grupowanie po mieście
da fałszywe duplikaty. Normalizuj do Title Case:

```python
# str.title() psuje polskie znaki i nazwy wieloczłonowe — użyj własnej funkcji
```
Zachowaj małe litery w spójnikach („nad", „i", „w").

**Nazwy — literówki i śmieci:** `Gospodarstw Rolne Piotr Duras` (brak „o"),
podwójne spacje (`Gospodarstwo Rolne  Bartosik Rafał`), ucięte nazwiska (`Bernard Mir`).
Zredukuj wielokrotne spacje i przytnij końce. **Nie poprawiaj literówek automatycznie** —
oznacz podejrzane rekordy tagiem do ręcznego przeglądu.

**Kod pocztowy:** format `XX-XXX`. Pięć cyfr bez myślnika → dodaj myślnik.

**Adresy niespójne z miastem:** rekord ma miasto `DOBRZYCA`, ulicę `Karmin`, kod `63-330`.
To normalne dla wsi w gminie — nie traktuj jako błędu, nie „popraw".

**Akroniny w dwóch seriach:** czterocyfrowe (`0156`–`0340`) i pięciocyfrowe (`10009`+).
Zawsze string.

### Sposób importu

Zrób **stronę `/import`**, nie skrypt CLI — import będzie powtarzany.

1. Upload pliku `.ods` / `.xlsx`
2. **Podgląd przed zapisem:** pierwsze 20 wierszy po normalizacji obok wartości
   oryginalnych, plus licznik problemów (ile telefonów nieparsowalnych, ile NIP-ów
   błędnych, ile potencjalnych duplikatów)
3. Potwierdzenie → zapis w transakcji
4. Raport: dodano / zaktualizowano / pominięto / wymaga weryfikacji

**Deduplikacja** — kolejność sprawdzania: `acronym` → `nip` (jeśli poprawny) →
dokładne dopasowanie `phone.e164` → dopiero na końcu podobieństwo nazwy
(`rapidfuzz`, próg wysoki, wynik tylko do oznaczenia, nie do automatycznego scalania).
Przy trafieniu **aktualizuj**, nie twórz duplikatu, i zapisz `Activity`
typu `CLIENT_UPDATED` z listą zmienionych pól.

Import 2000 wierszy może przekroczyć limit czasu żądania — wykonaj go w zadaniu
APScheduler i pokaż postęp przez HTMX z odpytywaniem co 2 sekundy.

---

## 6. Ekrany

Wszystkie renderowane serwerowo (Jinja2). Interaktywność przez HTMX: fragment HTML
z serwera zamiast JSON-a i JS-a. Alpine.js tylko tam, gdzie stan musi żyć w przeglądarce
(licznik znaków SMS, zaznaczanie wierszy).

### `/` — Dashboard
Liczniki: klienci ogółem, nowi w tym miesiącu, rozmowy do przejrzenia (`NEEDS_REVIEW`),
nadchodzące wydarzenia (7 dni), ostatnia kampania. Pod spodem ostatnie 20 wpisów
`Activity` z całego systemu.

### `/clients` — Lista
Tabela: Nazwa | Miasto | Telefon główny | Tagi | Ostatni kontakt | Status.
Wyszukiwarka (nazwa, NIP, telefon, miasto) — **wyszukiwanie po telefonie musi działać
niezależnie od formatu wpisanego przez użytkownika**: `601092947`, `601-092-947`
i `+48601092947` dają ten sam wynik. Znormalizuj zapytanie przed odpytaniem bazy.

Filtry: miasto, tag, status, ma-email, ma-telefon. Paginacja serwerowa po 50.
Zaznaczanie wierszy (Alpine) → „Wyślij SMS do zaznaczonych".

Wyszukiwarka i filtry przez HTMX — `hx-get` z `hx-trigger="keyup changed delay:300ms"`,
podmiana samego `<tbody>`.

### `/clients/<id>` — Panel klienta ⭐ główny ekran
Dwie kolumny.

**Lewa (dane):** nazwa, akronim, status, tagi (dodawanie/usuwanie inline).
Dane teleadresowe z **edycją inline** — każde pole osobno, przez HTMX: kliknięcie
podmienia `<span>` na `<input>` (`hx-get`), zapis wraca renderowanym `<span>`
(`hx-put`). Bez przeładowania strony i bez pisania JS-a.
Lista numerów: dodaj / usuń / ustaw jako główny. Czerwona ikona przy niepoprawnym NIP.
Przełącznik zgody SMS z datą.

**Prawa (oś czasu):** chronologiczna lista `Activity` — notatki, SMS-y, rozmowy, zmiany
danych, wydarzenia razem. Każdy typ z własną ikoną; wpisy AI wizualnie odróżnione
od ręcznych. Pole „dodaj notatkę" na górze. Przycisk „dodaj akcję ręcznie"
(`MANUAL`) — np. „wysłano ofertę pocztą". Transkrypcje rozwijalne: domyślnie
podsumowanie AI, kliknięcie dociąga pełny tekst przez HTMX.

### `/campaigns` — Kampanie SMS
Lista + kreator (sekcja 8).

### `/calendar` — Kalendarz
FullCalendar z CDN, zasilany endpointem JSON. Widoki: miesiąc, tydzień, agenda.
Wydarzenia z AI (`source=AI`, `confirmed=False`) — przerywana obwódka, przygaszony
kolor. Kliknięcie otwiera panel (HTMX) z fragmentem transkrypcji, z której powstały,
i przyciskami Potwierdź / Edytuj / Usuń.

### `/transcripts` — Rozmowy
Lista z filtrem po statusie. Osobna zakładka „Wymagają uwagi" (`NEEDS_REVIEW`, `FAILED`)
— rozmowy bez przypisanego klienta albo nieprzetworzone. Ręczne przypisanie do klienta
z tego widoku. Przycisk „przetwórz ponownie".

### `/import`
Patrz sekcja 5.

### `/settings`
Klucze API (maskowane). Pole nadawcy jako **lista rozwijana zasilana z `getSenderFields`**,
nie pole tekstowe. Stan konta z `getBalance`. Zarządzanie webhookiem doręczeń.
Regeneracja tokenu endpointu transkrypcji. Zużycie tokenów AI w bieżącym miesiącu.
Eksport bazy do CSV.

---

## 7. Autoryzacja

Jeden użytkownik. Flask-Login z klasą `User` **niebędącą modelem bazodanowym** —
login i hash hasła siedzą w zmiennych środowiskowych, tabela `users` jest zbędna.

```
ADMIN_LOGIN=Milosz
ADMIN_PASSWORD_HASH=<bcrypt>
```

Hash generuj skryptem `scripts/hash_password.py` (bcrypt, 12 rund). **Nigdy nie
umieszczaj hasła w postaci jawnej w kodzie, szablonie ani w tym pliku.**

- `@login_required` na wszystkich blueprintach poza `auth` i `api`
  (endpoint ingest i webhook mają własną autoryzację).
- Sesja trwała 30 dni, `SESSION_COOKIE_SECURE=True`, `HTTPONLY`, `SAMESITE=Lax`.
- Ochrona CSRF przez Flask-WTF na wszystkich formularzach. Żądania HTMX muszą wysyłać
  token — ustaw go globalnie przez `hx-headers` na `<body>`.
- Rate limiting na `/login`: 5 prób na 15 minut po adresie IP (`Flask-Limiter`,
  storage w pamięci wystarczy przy jednym procesie).
- Za proxy Railwaya włącz `ProxyFix`, inaczej rate limiting zobaczy jeden adres IP.

---

## 8. Kampanie SMS

### Adapter dostawcy

Interfejs w `app/services/sms/base.py`, implementacja obok. Wybór przez `SMS_PROVIDER`.

```python
class SmsProvider(Protocol):
    def send(self, req: SendRequest) -> SendResult: ...
    def cancel(self, provider_id: str) -> bool: ...
    def get_balance(self) -> int: ...
    def get_sender_fields(self) -> list[str]: ...
    def count_parts(self, text: str) -> int: ...      # liczone lokalnie, bez sieci
    def blacklist_add(self, phone: str, valid_to: date | None = None) -> bool: ...
    def blacklist_remove(self, phone: str) -> bool: ...
```

`SendRequest` (Pydantic): `to: list[str]` (do 10 000), `text`, `from_`, `params:
list[list[str]] | None` (maks. 4 kolumny, maks. 100 wierszy), `scheduled_at`,
`clear_polish`, `test`, `name`.

`SendResult`: sukces → `provider_id`, `buffered`; błąd → `error_code`, `error_message`.

### Implementacja: SMSPlanet.pl (API v2.3.0)

**Nie instaluj biblioteki** — oficjalne SDK są tylko dla PHP i Javy. `httpx` wystarczy.

```
Base URL:      https://api2.smsplanet.pl
Content-Type:  application/x-www-form-urlencoded    ← NIE JSON
Kodowanie:     UTF-8
Autoryzacja:   Authorization: Bearer <token>        ← zalecane, nie key+password
```

| Cel | Endpoint |
|---|---|
| Wysyłka SMS | `POST /sms` |
| Anulowanie zaplanowanej wysyłki | `POST /cancelMessage` |
| Szczegóły wysyłki | `POST /getMessageInfo` |
| Stan konta (tylko PrePaid) | `POST /getBalance` |
| Lista pól nadawcy | `POST /getSenderFields` |
| Zgłoszenie pola nadawcy | `POST /addSenderField` |
| Czarna lista | `POST /blacklist/add`, `/blacklist/remove` |
| Skracanie linków | `POST /shortUrl` |
| Webhooki | `POST /webhooks/create`, `/remove`, `GET /webhooks/list` |

Odpowiedzi w JSON: sukces `{"messageId":"191919"}` albo `{"result":"OK"}`,
błąd `{"errorMsg":"...","errorCode":101}`.

#### Parametry `POST /sms`

| Parametr | Opis |
|---|---|
| `from` | pole nadawcy, maks. 11 znaków, wymaga akceptacji; `TEST` działa zawsze |
| `msg` | treść; 160 znaków na część, 70 gdy występuje choć jeden polski znak; **maks. 6 części** |
| `to` | numer odbiorcy, parametr **powtarzalny**; do 10 000 na żądanie |
| `date` | `dd-MM-yyyy HH:mm:ss` albo Unixtime; **polska strefa czasowa** |
| `name` | nazwa wysyłki w historii dostawcy |
| `clear_polish` | `1` = zamiana diakrytyków na odpowiedniki ASCII |
| `param1`–`param4` | personalizacja, wartości rozdzielone `\|` |
| `test` | `1` = pełna walidacja bez wysyłki i bez opłaty |
| `transactional` | `1` = kanał transakcyjny, tylko wiadomości niemarketingowe |

**Format numeru:** API przyjmuje `600111222`, `48600111222` i `+48600111222`.
Wysyłaj E.164 prosto z bazy — żadnej konwersji.

**`to` jest parametrem powtarzalnym, nie listą po przecinku.** W `httpx` przekaż listę
krotek, nie słownik:
```python
data = [("from", sender), ("msg", text)] + [("to", n) for n in numbers]
```
Słownik nadpisze klucz `to` i wyśle jeden numer zamiast dwóch tysięcy.

#### Personalizacja

W UI użytkownik pisze `{{name}}`, `{{city}}`. Dostawca oczekuje `[%param1%]`
z wartościami rozdzielonymi pionową kreską. Tłumaczy adapter.

```
UI:   "Dzień dobry {{name}}, zapraszamy na pokaz w {{city}}."
API:  msg=Dzień dobry [%param1%], zapraszamy na pokaz w [%param2%].
      param1=Gabryś Ewa i Jerzy|SKR w Stawiszynie|...
      param2=Czajków|Stawiszyn|...
```

Trzy twarde ograniczenia wymuszone w UI:

1. **Maksymalnie 4 placeholdery** — kreator blokuje piąty.
2. **Maksymalnie 100 odbiorców na żądanie przy personalizacji.** 2000 osób
   z placeholderami = 20 żądań; bez placeholderów = jedno.
3. **Liczba wartości w każdym parametrze musi równać się liczbie numerów.**
   Brak miasta → pusty string, nie pominięta pozycja.

Escapuj `|` w wartościach, jeśli wystąpi w nazwie klienta.

#### Strategia wysyłki

**Nie buduj kolejki ani crona.** Limity API są na tyle wysokie, że cała kampania
mieści się w jednym–dwudziestu żądaniach.

| Przypadek | Sposób |
|---|---|
| Bez personalizacji, 2000 odbiorców | **jedno** żądanie z 2000 parametrami `to` |
| Z personalizacją, 2000 odbiorców | 20 żądań po 100, sekwencyjnie, zapis `CampaignBatch` |
| Wysyłka zaplanowana | parametr `date` — planowanie po stronie dostawcy |

Limity: 1000 żądań/min dla wysyłek, 300/min dla reszty; przekroczenie = blokada na 60 s.
Przy 20 żądaniach nie ma szans tego dotknąć.

Samą wysyłkę odpal jako zadanie APScheduler, żeby żądanie HTTP nie czekało — postęp
pokaż przez HTMX z odpytywaniem.

**Ponawianie:** dokumentacja wprost tego wymaga. Odpowiedź inna niż `200 OK`
z `messageId` → ponów po ~5 s, z rosnącym odstępem, do maks. ~10 minut.

**Bufor kolejkowy:** `messageId` zaczynający się od `B-` (np. `B-5-123456789`) oznacza,
że wiadomość trafiła do bufora i wyjdzie z opóźnieniem 10–30 s. Takiego identyfikatora
**nie da się użyć do anulowania** — ustaw `CampaignBatch.buffered = True` i ukryj
przycisk anulowania dla tej paczki.

#### Kody błędów — mapuj na działanie

| Kod | Znaczenie | Co zrobić w UI |
|---|---|---|
| 103, 113 | niepoprawne pole nadawcy | odeślij do `/settings` z listą dostępnych pól |
| 104 | wiadomość dłuższa niż 6 części | zablokuj już na etapie podglądu |
| 105 | wyczerpany limit wysyłek | komunikat, bez ponawiania |
| 106 | pusta lista odbiorców (wszyscy na czarnej liście) | pokaż, ilu odfiltrowano |
| 109 | brak środków | pokaż stan konta z `getBalance` |
| 110 | IP spoza listy dozwolonych | patrz uwaga niżej |
| 111 | powyżej 10 000 odbiorców | podziel na paczki |
| 201–203 | token nieprawidłowy / nieaktywny / wygasły | komunikat o odnowieniu tokenu |

Pełna lista to 100–115 i 200–203. Reszta → komunikat ogólny + log.

### Webhook doręczeń — zamiast odpytywania

`POST /webhooks/create` z `type=MESSAGE_NOTIFICATION_WEBHOOK`. Dostawca sam przysyła
status każdej wiadomości, więc **nie odpytuj `getMessageInfo` w pętli** (i tak
ograniczone do jednego wywołania na 3 minuty).

Endpoint `POST /api/webhooks/smsplanet`. Payload:

```json
{ "notification": {
    "messageId": "1234567", "from": "NOXSO", "to": "600700800",
    "delivered": "true", "parts": "1", "deliveryError": "",
    "sentDate": "24-05-2024 11:45:24", "deliveryDate": "24-05-2024 11:45:30"
} }
```

**Weryfikacja podpisu obowiązkowa** — endpoint jest publiczny. Nagłówek `Signature`
zawiera HMAC SHA256 z **surowego body**, zakodowany Base64, kluczem `Signature Key`
z panelu klienta.

```python
raw = request.get_data()          # surowe bajty, NIE json.dumps(request.json)
expected = base64.b64encode(
    hmac.new(SIGNATURE_KEY.encode(), raw, hashlib.sha256).digest()
).decode()
if not hmac.compare_digest(request.headers.get("Signature", ""), expected):
    abort(401)
```

Ponowna serializacja JSON-a zmieni bajty i podpis się nie zgodzi — czytaj `get_data()`
przed jakimkolwiek parsowaniem.

Po weryfikacji: znajdź `CampaignRecipient` po `phone_e164` + kampanii (przez
`CampaignBatch.provider_id`), ustaw `status`, `parts`, `delivered_at`, `delivery_error`,
dopisz `Activity`. **Zwróć 200** — inaczej dostawca ponawia przez ~16 godzin,
a po 500 nieudanych próbach usuwa webhook.

Statusy błędów doręczenia (1–11) zmapuj na opisy po polsku: wygaśnięcie, odrzucenie,
brak kanału, niedozwolona treść i pozostałe.

### Kreator kampanii

1. **Wybór odbiorców:** wszyscy / zaznaczeni / wg filtra
2. **Treść** z placeholderami — maksymalnie cztery, walidowane na bieżąco
3. **Podgląd na żywo:**
   - wyrenderowana treść na przykładowym odbiorcy
   - **licznik części po stronie przeglądarki** (Alpine.js): 160 znaków, 70 gdy
     w treści jest choć jeden polski znak, twardy limit 6 części. Istnieje endpoint
     `GET /sms/parts-count`, ale nie używaj go do podglądu na żywo — to zbędne żądanie
     przy każdym naciśnięciu klawisza. Wywołaj go raz, przy zapisie kampanii,
     do weryfikacji licznika.
   - przełącznik „usuń polskie znaki" → `clear_polish=1`, z porównaniem: ile części
     i ile złotych z diakrytykami, a ile bez
   - liczba odbiorców × liczba części = szacowany koszt, obok stanu konta
4. **Przebieg testowy** (`test=1`) na pełnej liście — **obowiązkowy**, odblokowuje
   przycisk wysyłki. Wynik do `Campaign.test_report`. Nie kosztuje nic.
5. **Wysyłka** — zapis `CampaignBatch` i `CampaignRecipient`, `Activity` na klientach
6. **Raport** — uzupełniany na bieżąco przez webhook

### Czarna lista — synchronizuj w dwie strony

Dostawca prowadzi własną czarną listę i odfiltrowuje te numery po swojej stronie
(błąd 106, gdy odfiltruje wszystkich). Ustawienie klientowi `status = BLACKLIST` ma
wywołać `blacklist/add`, zdjęcie statusu → `blacklist/remove`. Bez tego oba systemy
się rozjadą.

### Skracanie linków

`POST /shortUrl` zwraca link w domenie `wejdz.do` lub `link.do`. Przy limicie 70 znaków
na część długi URL potrafi dołożyć całą część do każdej wiadomości. Gdy kreator wykryje
URL dłuższy niż ~25 znaków, zaproponuj skrócenie i pokaż, ile części to oszczędza.

### Pole nadawcy

Maks. 11 znaków, dozwolone `a-z A-Z 0-9 . - + _ !` i spacja, numer telefonu niedozwolony.
`NOXSO` mieści się bez problemu. Zgłoszenie przez `addSenderField`, akceptacja
1–3 dni robocze. W `/settings` lista rozwijana z `getSenderFields`, nie pole tekstowe —
inaczej literówka da błąd 103 dopiero przy wysyłce. Do czasu akceptacji używaj `TEST`.

### Uwagi praktyczne

- Deduplikuj odbiorców po swojej stronie, mimo że API też to robi — `CampaignRecipient`
  ma odzwierciedlać rzeczywistość.
- Nigdy nie wysyłaj do `status = BLACKLIST` — filtruj przed zbudowaniem żądania.
- `transactional=1` **tylko** dla wiadomości niemarketingowych. Nie dawaj tego
  przełącznika w kreatorze kampanii.
- **Filtracja IP:** dostawca pozwala ograniczyć dostęp do listy adresów. Railway daje
  stabilniejsze adresy wyjściowe niż Vercel, ale nie gwarantuje statycznego IP —
  nie włączaj domyślnie, odnotuj w README jako opcję.

### Alternatywy

Gdyby zaszła potrzeba: SMSAPI.pl (droższy, lepsza dokumentacja), SerwerSMS.pl
(abonament). **Nie implementuj ich teraz.**

> **Kwestia prawna do sprawdzenia przez właściciela, nie przez Ciebie:** wysyłka SMS-ów
> marketingowych do abonentów wymaga w Polsce uprzedniej zgody (Prawo komunikacji
> elektronicznej). Pole `sms_consent` istnieje właśnie po to. Kreator kampanii domyślnie
> **filtruje odbiorców po `sms_consent = True`**, z możliwością świadomego wyłączenia
> filtra przez checkbox z ostrzeżeniem. Nie usuwaj tego mechanizmu.

---

## 9. Endpoint transkrypcji + analiza AI

### Endpoint

`POST /api/ingest/transcript`

Autoryzacja: nagłówek `Authorization: Bearer <INGEST_TOKEN>`. To jedyny endpoint poza
sesją użytkownika — kolega właściciela będzie tu wrzucał pliki. Porównuj token przez
`hmac.compare_digest`, nie zwykłym `==`.

Przyjmuje dwa warianty:
- `multipart/form-data` z polem `file` (`.txt`) + opcjonalnie `phone`, `date`
- `application/json`: `{"text": ..., "phone": ..., "date": ..., "filename": ...}`

Zachowanie:
1. Zapisz `Transcript` ze statusem `PENDING` i **natychmiast zwróć 202** z `{"id": ...}`.
   Nie każ klientowi czekać na model.
2. Przetwarzanie przejmuje APScheduler (niżej).

**Kodowanie:** pliki `.txt` mogą przyjść w CP1250 lub UTF-8. Wykryj (`charset-normalizer`,
jest zależnością `requests`) i zdekoduj do UTF-8 — inaczej polskie znaki się rozsypią.
Limit rozmiaru 1 MB (`MAX_CONTENT_LENGTH`), odrzuć większe z czytelnym komunikatem.

Wszystkie wejścia waliduj modelem Pydantic.

### Dopasowanie do klienta

Numer może przyjść w polu `phone` **albo być tylko w treści**. Kolejność:

1. Pole `phone` z żądania
2. Regex po treści — wzorce polskich numerów: `+48XXXXXXXXX`, `XXX XXX XXX`,
   `XXX-XXX-XXX`, dziewięć cyfr ciągiem
3. Normalizuj do E.164 (`phonenumbers`) i szukaj w `Phone.e164`

Wyniki:
- **Trafienie** → przypisz `client_id`
- **Brak trafienia, ale numer poprawny** → **utwórz klienta** (`source=TRANSCRIPT`,
  `name` = nazwa wyciągnięta przez AI albo tymczasowo numer, tag `nowy-z-rozmowy`),
  przypisz transkrypcję, dodaj `Activity`
- **Brak numeru** → `NEEDS_REVIEW`, bez klienta, do ręcznego przypisania

### Przetwarzanie w tle

Railway utrzymuje stały proces, więc wystarczy APScheduler:

```python
# co 30 sekund: pobierz transkrypcje PENDING i przetwórz
```

Ustaw `max_instances=1` i blokadę na poziomie bazy (`SELECT ... FOR UPDATE SKIP LOCKED`),
żeby przy większej liczbie workerów Gunicorna zadanie nie wykonało się kilka razy.
Alternatywnie: uruchom scheduler tylko w jednym workerze, sterując zmienną środowiskową.
**Przy jednym workerze Gunicorna problem znika — zacznij od `--workers 1`.**

### Analiza AI

DeepSeek przez SDK `openai` — API jest zgodne z OpenAI:

```python
from openai import OpenAI
client = OpenAI(api_key=os.environ["DEEPSEEK_API_KEY"],
                base_url="https://api.deepseek.com")
# model: "deepseek-chat"
```

Trzymaj za własnym interfejsem w `app/services/ai.py`, żeby dało się podmienić model.

Wymuś JSON (`response_format={"type": "json_object"}`) i **zwaliduj odpowiedź
modelem Pydantic** przed zapisem. Model ma zwrócić:

```jsonc
{
  "summary": "2–3 zdania po polsku, o czym była rozmowa",
  "client_name": "nazwa firmy/osoby jeśli padła, inaczej null",
  "sentiment": "positive | neutral | negative",
  "outcome": "zainteresowany | brak zainteresowania | do oddzwonienia | umówiono spotkanie | inne",
  "events": [
    {
      "title": "krótki tytuł",
      "description": "kontekst z rozmowy",
      "date": "2026-03-14",      // ISO, null jeśli nieokreślona
      "time": "14:00",           // null jeśli nie padła
      "confidence": "high | medium | low"
    }
  ],
  "follow_up_needed": true,
  "key_points": ["...", "..."]
}
```

**Prompt musi zawierać dzisiejszą datę** — w rozmowach padają określenia względne
(„w przyszły wtorek", „za dwa tygodnie", „pod koniec miesiąca"). Bez daty odniesienia
model wygeneruje bezsensowne terminy. Prompt po polsku — transkrypcje są po polsku,
z gwarą i skrótami branżowymi.

Z każdego zdarzenia twórz `CalendarEvent` z `source=AI`, `confirmed=False`.
**Nigdy nie zapisuj wydarzeń z AI jako potwierdzonych.** `confidence="low"` oznacz
dodatkowo w opisie.

**Błędy:** licz `attempts`, 3 próby z rosnącym odstępem, potem `FAILED` + zapis błędu.
Przycisk „przetwórz ponownie" w UI. Surowy tekst zostaje w bazie zawsze — nawet gdy
AI zawiodło, treść rozmowy musi być dostępna.

**Kontrola kosztów:** zapisuj `tokens_used` z odpowiedzi API i pokaż sumę miesięczną
w `/settings`. DeepSeek jest tani, ale przy kilkudziesięciu rozmowach dziennie warto
widzieć trend.

---

## 10. Zmienne środowiskowe

```bash
FLASK_ENV=production
SECRET_KEY=                  # losowy, min. 32 bajty
DATABASE_URL=                # postgresql+psycopg://...
TZ=Europe/Warsaw

ADMIN_LOGIN=Milosz
ADMIN_PASSWORD_HASH=         # bcrypt, generuj scripts/hash_password.py

SMS_PROVIDER=smsplanet
SMSPLANET_TOKEN=             # panel klienta → API → Tokeny API
SMSPLANET_SIGNATURE_KEY=     # panel klienta → API → Webhooki
SMS_SENDER_NAME=NOXSO        # maks. 11 znaków; do czasu akceptacji: TEST

DEEPSEEK_API_KEY=
AI_MODEL=deepseek-chat

INGEST_TOKEN=                # token endpointu transkrypcji
```

Dołóż `.env.example` z komentarzami oraz `scripts/hash_password.py`.
`DATABASE_URL` z Railwaya przychodzi z prefiksem `postgres://` — SQLAlchemy 2.0 wymaga
`postgresql+psycopg://`, więc podmień prefiks w `config.py`.

---

## 11. Kolejność prac

Rób etapami. **Po każdym zatrzymaj się, pokaż efekt i poczekaj na akceptację.**

1. **Fundament** — app factory, konfiguracja, SQLAlchemy + Alembic, modele, pierwsza
   migracja, Flask-Login, layout Jinja z paletą NOXSO, Tailwind standalone, pusty dashboard
2. **Import** — parser `.ods`, normalizacja (telefony, NIP, miasta, kody), deduplikacja,
   `/import` z podglądem i postępem, **testy jednostkowe normalizatorów**
3. **Klienci** — lista z wyszukiwarką i filtrami (HTMX), panel klienta, edycja inline,
   notatki, oś czasu, tagi
4. **Transkrypcje** — endpoint ingest, dopasowanie po numerze, auto-tworzenie klientów,
   `/transcripts`
5. **AI** — DeepSeek, prompt z datą, walidacja Pydantikiem, generowanie wydarzeń,
   APScheduler, ponawianie
6. **Kalendarz** — FullCalendar, wydarzenia AI vs ręczne, potwierdzanie
7. **SMS** — adapter SMSPlanet, kreator kampanii, licznik części, przebieg testowy,
   wysyłka, webhook doręczeń z weryfikacją podpisu, synchronizacja czarnej listy, raporty
8. **Wykończenie** — `/settings`, eksport CSV, obsługa błędów, deploy na Railway

---

## 12. Zasady pracy

- **Pytaj, gdy specyfikacja jest niejednoznaczna.** Lepsze jedno pytanie niż tydzień
  pracy w złym kierunku.
- **Nie dodawaj funkcji, których tu nie ma.** Bez portalu klienta, fakturowania,
  integracji z pocztą, powiadomień push, trybu ciemnego — chyba że padnie osobna prośba.
- **Piszesz dla kogoś, kto zna Pythona, a nie zna JavaScriptu.** Gdy potrzebna jest
  interaktywność, sięgaj najpierw po HTMX (fragment HTML z serwera), potem po Alpine.js,
  a własny JS pisz tylko wtedy, gdy nie ma innego wyjścia — i wtedy komentuj po polsku.
- **Testy jednostkowe (pytest) dla:** normalizacji danych (telefony, NIP, miasta, kody
  pocztowe), licznika części SMS (GSM-7 vs UCS-2, granica 6 części), mapowania
  placeholderów na `param1`–`param4` (zgodność liczby wartości z liczbą numerów)
  i parsowania odpowiedzi AI. To miejsca, gdzie błąd cicho zepsuje 2000 rekordów albo
  kosztuje realne pieniądze. Reszty na tym etapie nie testuj.
- **Nie usuwaj i nie nadpisuj danych bez potwierdzenia.** Usunięcie klienta = dialog
  z wpisaniem nazwy. Import nigdy nie kasuje istniejących rekordów.
- Wszystkie daty w bazie w UTC (`DateTime(timezone=True)`), wyświetlane
  w `Europe/Warsaw`. Uwaga: SMSPlanet planuje wysyłki wg czasu polskiego — konwertuj.
- Waliduj Pydantikiem każde wejście, także z formularzy.
- Typuj wszystko (`mypy` w trybie podstawowym), formatuj `ruff`.
- Commituj po każdym etapie, po angielsku, w konwencji conventional commits.
