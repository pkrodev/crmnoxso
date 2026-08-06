"""Generator hasha hasła do zmiennej ADMIN_PASSWORD_HASH.

    python scripts/hash_password.py

Hasło wpisujesz w ukryciu (nie pojawia się na ekranie ani w historii poleceń).
Wynik wklejasz do pliku .env. Hasła w postaci jawnej nie trzymamy nigdzie —
ani w kodzie, ani w szablonach, ani w dokumentacji.
"""

from __future__ import annotations

import getpass
import sys

import bcrypt

ROUNDS = 12
MIN_LENGTH = 10


def main() -> int:
    print("Generator hasha hasła (bcrypt, 12 rund)\n")

    password = getpass.getpass("Hasło: ")
    if len(password) < MIN_LENGTH:
        print(f"\nHasło musi mieć co najmniej {MIN_LENGTH} znaków.", file=sys.stderr)
        return 1

    repeated = getpass.getpass("Powtórz hasło: ")
    if password != repeated:
        print("\nHasła się różnią.", file=sys.stderr)
        return 1

    digest = bcrypt.hashpw(password.encode("utf-8"), bcrypt.gensalt(rounds=ROUNDS))

    print("\nWklej tę linię do pliku .env:\n")
    print(f"ADMIN_PASSWORD_HASH={digest.decode('utf-8')}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
