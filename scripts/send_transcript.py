"""Wysyła transkrypcję na endpoint ingest — do ręcznego sprawdzenia etapu 4.

    python scripts/send_transcript.py --tekst "Dzień dobry, tu Kowalski..."
    python scripts/send_transcript.py rozmowa.txt --telefon "601 092 947"
    python scripts/send_transcript.py rozmowa.txt --data 14.03.2026

Token bierze z pliku ``.env`` (zmienna ``INGEST_TOKEN``) — nie trzeba go
wklejać w wiersz poleceń ani pamiętać. Adres serwera z ``--adres``, domyślnie
lokalny.

Powstało dlatego, że w PowerShellu ``curl`` jest aliasem ``Invoke-WebRequest``
o zupełnie innej składni, a cudzysłowy w JSON-ie trzeba tam escapować tak, że
polecenie przestaje być czytelne. To jest to samo żądanie, tylko po ludzku.
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

import httpx
from dotenv import dotenv_values

PROJECT_ROOT = Path(__file__).resolve().parent.parent

# Konsola Windowsa domyślnie nie jest w UTF-8 — bez tego polskie znaki
# w odpowiedzi serwera wyświetlą się jako krzaki, choć w bazie są poprawne.
if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "plik",
        nargs="?",
        type=Path,
        help="plik .txt z transkrypcją (albo użyj --tekst)",
    )
    parser.add_argument("--tekst", help="treść rozmowy wpisana wprost")
    parser.add_argument("--telefon", help="numer rozmówcy w dowolnym zapisie")
    parser.add_argument("--data", help="data rozmowy: 14.03.2026 albo 2026-03-14")
    parser.add_argument(
        "--adres",
        default="http://127.0.0.1:5000",
        help="adres aplikacji (domyślnie serwer deweloperski)",
    )
    parser.add_argument(
        "--token",
        help="token endpointu; domyślnie INGEST_TOKEN z pliku .env",
    )
    args = parser.parse_args()

    if not args.plik and not args.tekst:
        parser.error("Podaj plik z transkrypcją albo --tekst.")

    token = args.token or dotenv_values(PROJECT_ROOT / ".env").get("INGEST_TOKEN")
    if not token:
        print(
            "Brak tokenu. Ustaw INGEST_TOKEN w pliku .env albo podaj --token.\n"
            'Wygenerujesz go tak: python -c "import secrets; print(secrets.token_urlsafe(32))"',
            file=sys.stderr,
        )
        return 2

    url = args.adres.rstrip("/") + "/api/ingest/transcript"
    headers = {"Authorization": f"Bearer {token}"}

    try:
        if args.plik:
            if not args.plik.exists():
                print(f"Nie ma pliku {args.plik}", file=sys.stderr)
                return 2
            # Plik idzie surowymi bajtami — kodowanie rozpoznaje serwer,
            # dokładnie tak jak przy wrzutce z zewnątrz.
            files = {"file": (args.plik.name, args.plik.read_bytes(), "text/plain")}
            form = {
                key: value
                for key, value in (("phone", args.telefon), ("date", args.data))
                if value
            }
            response = httpx.post(url, headers=headers, files=files, data=form)
        else:
            payload: dict[str, str] = {"text": args.tekst}
            if args.telefon:
                payload["phone"] = args.telefon
            if args.data:
                payload["date"] = args.data
            response = httpx.post(url, headers=headers, json=payload)
    except httpx.ConnectError:
        print(
            f"Nie ma połączenia z {args.adres}. Czy aplikacja działa?\n"
            "  .venv\\Scripts\\flask.exe run --debug",
            file=sys.stderr,
        )
        return 1

    print(f"HTTP {response.status_code}")
    try:
        body = response.json()
    except ValueError:
        print(response.text[:500])
        return 0 if response.is_success else 1

    print(json.dumps(body, ensure_ascii=False, indent=2))

    if response.status_code == 202 and body.get("id"):
        print(f"\nRozmowa: {args.adres.rstrip('/')}/transcripts/{body['id']}")
        if body.get("client_id"):
            print(f"Klient:  {args.adres.rstrip('/')}/clients/{body['client_id']}")

    return 0 if response.is_success else 1


if __name__ == "__main__":
    raise SystemExit(main())
