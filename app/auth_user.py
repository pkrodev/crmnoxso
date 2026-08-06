"""Jedyny użytkownik systemu.

Nie ma tabeli ``users`` — login i hash hasła siedzą w zmiennych środowiskowych
(sekcja 7 specyfikacji). Klienci NIGDY się nie logują, więc nie ma tu ról,
uprawnień ani rejestracji.
"""

from __future__ import annotations

import hmac

import bcrypt
from flask import current_app
from flask_login import UserMixin


class User(UserMixin):
    """Właściciel firmy. Zawsze jeden i ten sam."""

    def __init__(self, login: str) -> None:
        self.id = login
        self.login = login

    def get_id(self) -> str:
        return self.id

    @property
    def display_name(self) -> str:
        return self.login


def load_user(user_id: str) -> User | None:
    """Callback Flask-Login: odtworzenie użytkownika z sesji."""
    expected = current_app.config.get("ADMIN_LOGIN", "")
    if expected and hmac.compare_digest(user_id, expected):
        return User(expected)
    return None


def verify_credentials(login: str, password: str) -> User | None:
    """Sprawdzenie loginu i hasła.

    Login porównujemy przez ``compare_digest``, a hash zawsze weryfikujemy —
    także przy złym loginie — żeby czas odpowiedzi nie zdradzał, która część
    była błędna.
    """
    expected_login = current_app.config.get("ADMIN_LOGIN", "")
    expected_hash = current_app.config.get("ADMIN_PASSWORD_HASH", "")

    if not expected_login or not expected_hash:
        current_app.logger.error(
            "Brak ADMIN_LOGIN lub ADMIN_PASSWORD_HASH w konfiguracji — "
            "logowanie niemożliwe. Uzupełnij plik .env."
        )
        return None

    login_ok = hmac.compare_digest(login.strip(), expected_login)

    try:
        password_ok = bcrypt.checkpw(
            password.encode("utf-8"), expected_hash.encode("utf-8")
        )
    except ValueError:
        current_app.logger.error(
            "ADMIN_PASSWORD_HASH nie jest poprawnym hashem bcrypt. "
            "Wygeneruj go poleceniem: python scripts/hash_password.py"
        )
        return None

    return User(expected_login) if (login_ok and password_ok) else None
