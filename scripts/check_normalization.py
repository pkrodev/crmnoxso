"""Kontrola normalizacji na prawdziwym pliku — bez dotykania bazy danych.

    python scripts/check_normalization.py "poprawiona baza klientów ... .xlsx"
    python scripts/check_normalization.py plik.ods --pokaz-bledy

Przelatuje cały arkusz i pokazuje, co normalizator zrobił z danymi: ile numerów
udało się sparsować, ile NIP-ów przechodzi sumę kontrolną, które wartości
wymagają ręcznego przejrzenia. Przydatne przed każdym importem i po każdej
zmianie w regułach normalizacji.
"""

from __future__ import annotations

import argparse
import sys
from collections import Counter
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from app.services.importer import parse_sheet, read_sheet


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("plik", type=Path)
    parser.add_argument(
        "--pokaz-bledy",
        action="store_true",
        help="wypisz wszystkie wartości, których nie udało się znormalizować",
    )
    parser.add_argument("--limit", type=int, default=25, help="ile przykładów pokazać")
    args = parser.parse_args()

    if not args.plik.exists():
        print(f"Nie znaleziono pliku: {args.plik}", file=sys.stderr)
        return 1

    sheet = read_sheet(args.plik)
    rows = parse_sheet(sheet)
    data = [row for row in rows if not row.empty]

    print(f"Plik:            {args.plik.name}")
    print(f"Nagłówki:        wiersz {sheet.header_row + 1}")
    print(f"Kolumny:         {', '.join(sorted(sheet.columns))}")
    pominiete = [
        label
        for label in sheet.unmapped
        if label.lower().strip(". ") in {"prefiks", "opiekun"}
    ]
    if pominiete:
        print(f"Pominięte:       {', '.join(pominiete)}")
    print(f"Wierszy z danymi:{len(data):>6}")
    print(f"Wierszy pustych: {len(rows) - len(data):>6}")
    print()

    phones = [phone for row in data for phone in row.phones]
    valid_phones = [p for p in phones if p.is_valid]
    print("TELEFONY")
    print(f"  komórek z numerem      {sum(1 for r in data if r.raw.get('phone')):>6}")
    print(f"  wyłuskanych numerów    {len(phones):>6}")
    print(f"  sparsowanych           {len(valid_phones):>6}")
    print(f"  nieparsowalnych        {len(phones) - len(valid_phones):>6}")
    print(f"  wierszy bez numeru     {sum(1 for r in data if not r.valid_phones):>6}")
    multi = sum(1 for r in data if len(r.valid_phones) > 1)
    print(f"  wierszy z 2+ numerami  {multi:>6}")
    shared = Counter(p.e164 for p in valid_phones)
    print(f"  numerów u >1 klienta   {sum(1 for c in shared.values() if c > 1):>6}")
    print()

    with_nip = [r for r in data if r.raw.get("nip")]
    print("NIP")
    print(f"  wypełnionych           {len(with_nip):>6}")
    print(f"  poprawnych             {sum(1 for r in with_nip if r.nip_valid):>6}")
    print(f"  błędnych               {sum(1 for r in with_nip if not r.nip_valid):>6}")
    nips = Counter(r.values["nip"] for r in with_nip if r.nip_valid)
    print(f"  powtórzonych           {sum(1 for c in nips.values() if c > 1):>6}")
    print()

    changed_cities = sum(
        1 for r in data if r.raw.get("city") and r.raw["city"] != r.values.get("city")
    )
    unique_before = len({r.raw.get("city") for r in data if r.raw.get("city")})
    unique_after = len({r.values.get("city") for r in data if r.values.get("city")})
    print("MIASTA")
    print(f"  poprawionych zapisów   {changed_cities:>6}")
    print(f"  unikalnych przed       {unique_before:>6}")
    print(f"  unikalnych po          {unique_after:>6}")
    print(f"  scalonych wariantów    {unique_before - unique_after:>6}")
    print()

    bad_postal = [
        r for r in data if r.raw.get("postal_code") and not r.values.get("postal_code")
    ]
    bad_email = [r for r in data if r.raw.get("email") and not r.values.get("email")]
    print("POZOSTAŁE")
    print(f"  błędnych kodów poczt.  {len(bad_postal):>6}")
    print(f"  błędnych adresów email {len(bad_email):>6}")
    print(f"  wierszy do weryfikacji {sum(1 for r in data if r.needs_review):>6}")
    acronyms = Counter(r.values.get("acronym") for r in data if r.values.get("acronym"))
    print(f"  powtórzonych akronimów {sum(1 for c in acronyms.values() if c > 1):>6}")
    print()

    if args.pokaz_bledy:
        print("NIEPARSOWALNE NUMERY")
        for phone in [p for p in phones if not p.is_valid][: args.limit]:
            print(f"  {phone.raw!r:40} {phone.warning}")
        print()
        print("BŁĘDNE NIP-Y")
        for row in [r for r in with_nip if not r.nip_valid][: args.limit]:
            print(f"  wiersz {row.number:5}  {row.raw['nip']!r}")
        print()
        print("BŁĘDNE KODY POCZTOWE")
        for row in bad_postal[: args.limit]:
            print(f"  wiersz {row.number:5}  {row.raw['postal_code']!r}")

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
