# Wrzucanie transkrypcji rozmów do NOXSO CRM

Dokument dla osoby, która wysyła zapisy rozmów telefonicznych do systemu.
Wystarczy jedno żądanie HTTP — nie trzeba konta, logowania ani przeglądarki.

---

## Adres

```
POST https://noxso-crm-production.up.railway.app/api/ingest/transcript
```

Autoryzacja nagłówkiem:

```
Authorization: Bearer <TOKEN>
```

**Token dostaniesz osobno.** Nie ma go w tym dokumencie i nie wysyłaj go
kanałem, który ktoś jeszcze czyta — kto ma token, może dopisywać rozmowy
i zakładać klientów w cudzej bazie.

---

## Dwa warianty żądania

Oba robią dokładnie to samo. Wybierz wygodniejszy.

### A. Plik `.txt` (multipart/form-data)

```bash
curl -X POST https://noxso-crm-production.up.railway.app/api/ingest/transcript \
  -H "Authorization: Bearer TOKEN" \
  -F "file=@rozmowa.txt" \
  -F "phone=601 092 947" \
  -F "date=26.08.2026"
```

| Pole | Wymagane | Opis |
|---|---|---|
| `file` | tak | plik z zapisem rozmowy |
| `phone` | nie | numer rozmówcy |
| `date` | nie | data rozmowy |
| `filename` | nie | nazwa do pokazania na liście; domyślnie nazwa pliku |

### B. JSON

```bash
curl -X POST https://noxso-crm-production.up.railway.app/api/ingest/transcript \
  -H "Authorization: Bearer TOKEN" \
  -H "Content-Type: application/json" \
  -d '{"text": "zapis rozmowy...", "phone": "601092947", "date": "2026-08-26"}'
```

| Pole | Wymagane | Opis |
|---|---|---|
| `text` | tak | zapis rozmowy |
| `phone` | nie | numer rozmówcy |
| `date` | nie | data rozmowy |
| `filename` | nie | nazwa do pokazania na liście |

W Pythonie:

```python
import httpx

with open("rozmowa.txt", "rb") as f:
    r = httpx.post(
        "https://noxso-crm-production.up.railway.app/api/ingest/transcript",
        headers={"Authorization": f"Bearer {TOKEN}"},
        files={"file": ("rozmowa.txt", f.read(), "text/plain")},
        data={"phone": "601 092 947", "date": "26.08.2026"},
        timeout=30,
    )
print(r.status_code, r.json())
```

---

## Zasady, o które nie musisz się martwić

- **Numer w dowolnym zapisie.** `601092947`, `601-092-947`, `601 092 947`,
  `+48601092947`, `48601092947` — wszystko jedno. Stacjonarne też.
- **Data po polsku albo po ISO.** `26.08.2026` i `2026-08-26` są równoważne.
  Przyjmiemy też `26-08-2026` i znacznik czasu ISO (weźmiemy z niego sam dzień).
- **Kodowanie pliku wykrywamy sami.** CP1250 i UTF-8 działają tak samo, polskie
  znaki nie rozsypią się. Nie musisz niczego konwertować.
- **Numeru można nie podawać.** Jeśli pominiesz `phone`, system spróbuje wyłuskać
  numer z treści rozmowy. Rozpoznaje typowe zapisy i nie pomyli numeru z NIP-em,
  datą ani kwotą.
- **Data też jest opcjonalna.** Bez niej rozmowa trafi na oś czasu z chwilą
  wysłania.

## Ograniczenia

| | |
|---|---|
| Rozmiar | 1 MB na rozmowę |
| Tempo | 120 żądań na minutę |
| Format pliku | zwykły tekst (`.txt`) |

---

## Co przychodzi w odpowiedzi

Sukces to **`202`**, i przychodzi **natychmiast** — nie czekamy na analizę,
ona leci po naszej stronie w tle.

```json
{
  "id": 42,
  "status": "PENDING",
  "client_id": 17,
  "client_created": false,
  "phone": "+48601092947",
  "message": "Numer 601 092 947 należy do klienta „Gospodarstwo Rolne Kowalski”."
}
```

| Pole | Znaczenie |
|---|---|
| `id` | numer rozmowy w systemie |
| `status` | `PENDING` — czeka na analizę; `NEEDS_REVIEW` — nie dało się przypisać klienta |
| `client_id` | do kogo przypięto rozmowę; `null`, gdy nie ustalono |
| `client_created` | `true`, gdy numer był nieznany i założono nowego klienta |
| `message` | zdanie po polsku, co się stało — warto zalogować |

`status: NEEDS_REVIEW` **nie jest błędem po Twojej stronie.** Znaczy tylko, że
rozmowa czeka na ręczne przypisanie klienta — bo nie było numeru albo numer
należy do kilku gospodarstw. Treść rozmowy jest zapisana i nic nie ginie.

### Kody błędów

| Kod | Znaczenie | Co zrobić |
|---|---|---|
| `401` | zły token albo brak nagłówka | sprawdź token, nie ponawiaj w pętli |
| `400` | pusty plik albo treść nie jest JSON-em | popraw żądanie |
| `413` | ponad 1 MB | podziel rozmowę albo przytnij |
| `422` | brak `text`, pusty tekst, nieznany format daty | odpowiedź zawiera `details` z nazwą pola |
| `429` | przekroczone 120 żądań na minutę | odczekaj minutę |
| `503` | endpoint nieskonfigurowany po stronie serwera | daj znać właścicielowi |

Błędy zwracamy jako JSON: `{"error": "opis po polsku"}`.

---

## Rzeczy, o których warto wiedzieć

- **Nie ma odsiewania duplikatów.** Ta sama rozmowa wysłana dwa razy da dwa
  wpisy. Jeśli ponawiasz po błędzie sieci, upewnij się, że poprzednie żądanie
  faktycznie nie doszło — `202` znaczy „przyjęte”.
- **To endpoint serwer-do-serwera.** Nie wywołuj go z przeglądarki, bo token
  byłby widoczny w kodzie strony.
- **Nie ma potrzeby czekania między rozmowami.** Możesz wysłać kilkadziesiąt
  pod rząd; kolejkę przerabiamy u siebie.
- Sprawdzenie, czy system żyje, bez tokenu:
  ```bash
  curl https://noxso-crm-production.up.railway.app/api/healthz
  ```
  Odpowiada `{"status":"ok", ...}`, dopóki aplikacja działa.

---

## Co dzieje się dalej, po naszej stronie

Żebyś wiedział, czemu odpowiedź wygląda tak, a nie inaczej:

1. Zapisujemy surowy tekst rozmowy — **zawsze**, nawet gdy dalsze kroki zawiodą.
2. Szukamy klienta po numerze. Nieznany numer zakłada nowego klienta; numer
   wspólny dla kilku gospodarstw trafia do ręcznego rozstrzygnięcia.
3. Zadanie w tle wysyła rozmowę do modelu językowego, który robi podsumowanie
   i wyciąga umówione terminy do kalendarza.

Stąd `202` zamiast `200`: przyjęliśmy rozmowę, ale przetwarzanie jeszcze trwa.
