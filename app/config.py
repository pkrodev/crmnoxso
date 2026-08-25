"""Konfiguracja aplikacji — wszystko z zmiennych środowiskowych."""

from __future__ import annotations

import os
from datetime import timedelta
from typing import Any, ClassVar

from dotenv import load_dotenv

# Wartości poniżej czytane są z otoczenia już w ciele klas, czyli w chwili
# importu tego modułu. Plik .env musi więc trafić do os.environ ZANIM
# którakolwiek klasa zostanie zdefiniowana — inaczej konfiguracja po cichu
# spada na wartości domyślne. Polecenie `flask` wczytuje .env samo, ale
# pytest, gunicorn i `python wsgi.py` już nie, więc robimy to tutaj.
load_dotenv()


def _secret(name: str, default: str = "") -> str:
    """Wartość ze zmiennej środowiskowej, oczyszczona z niewidzialnych śmieci.

    Sekrety trafiają do panelu hostingu przez schowek, a po drodze potrafi się
    do nich dokleić spacja, znak nowej linii albo **BOM** (``\\ufeff``). Kosztowało
    to już jedno popołudnie: hash bcrypta z BOM-em na początku ma 61 znaków
    zamiast 60, ``bcrypt.checkpw`` uznaje go za nieprawidłową sól i odrzuca
    KAŻDE hasło — a aplikacja mówi tylko „nieprawidłowy login lub hasło",
    bo celowo nie zdradza, która część zawiodła.
    """
    return os.environ.get(name, default).strip().lstrip("﻿").strip()


def _database_url() -> str:
    """Adres bazy, z podmianą prefiksu.

    Railway podaje ``DATABASE_URL`` w formie ``postgres://...``, a SQLAlchemy 2.0
    tego schematu już nie zna — wymaga ``postgresql+psycopg://``.
    """
    url = os.environ.get("DATABASE_URL", "")
    if url.startswith("postgres://"):
        url = url.replace("postgres://", "postgresql+psycopg://", 1)
    elif url.startswith("postgresql://"):
        url = url.replace("postgresql://", "postgresql+psycopg://", 1)
    return url


class Config:
    """Wspólna baza konfiguracji."""

    SECRET_KEY = _secret("SECRET_KEY")

    SQLALCHEMY_DATABASE_URI = _database_url()
    SQLALCHEMY_TRACK_MODIFICATIONS = False
    SQLALCHEMY_ENGINE_OPTIONS: ClassVar[dict[str, Any]] = {
        "pool_pre_ping": True,  # Railway ubija bezczynne połączenia
        "pool_recycle": 1800,
    }

    # Sesja
    PERMANENT_SESSION_LIFETIME = timedelta(days=30)
    SESSION_COOKIE_HTTPONLY = True
    SESSION_COOKIE_SAMESITE = "Lax"
    SESSION_COOKIE_SECURE = True
    REMEMBER_COOKIE_DURATION = timedelta(days=30)
    REMEMBER_COOKIE_HTTPONLY = True
    REMEMBER_COOKIE_SECURE = True

    # Limit rozmiaru żądania — dotyczy endpointu transkrypcji (sekcja 9 specyfikacji).
    # Upload arkusza na /import ma własny, wyższy limit sprawdzany w formularzu.
    MAX_CONTENT_LENGTH = 16 * 1024 * 1024
    INGEST_MAX_BYTES = 1 * 1024 * 1024
    IMPORT_MAX_BYTES = 10 * 1024 * 1024

    # Katalog na wgrane arkusze
    UPLOAD_DIR = os.environ.get(
        "UPLOAD_DIR", os.path.join(os.path.dirname(os.path.dirname(__file__)), "uploads")
    )

    # Użytkownik (jeden, bez tabeli w bazie — sekcja 7 specyfikacji)
    ADMIN_LOGIN = _secret("ADMIN_LOGIN")
    ADMIN_PASSWORD_HASH = _secret("ADMIN_PASSWORD_HASH")

    # Strefa czasowa prezentacji (w bazie wszystko w UTC)
    DISPLAY_TZ = os.environ.get("TZ", "Europe/Warsaw")

    # SMS (etap 7)
    SMS_PROVIDER = os.environ.get("SMS_PROVIDER", "smsplanet")
    SMSPLANET_TOKEN = _secret("SMSPLANET_TOKEN")
    SMSPLANET_SIGNATURE_KEY = _secret("SMSPLANET_SIGNATURE_KEY")
    SMS_SENDER_NAME = os.environ.get("SMS_SENDER_NAME", "TEST")

    # AI (etap 5)
    DEEPSEEK_API_KEY = _secret("DEEPSEEK_API_KEY")
    AI_MODEL = os.environ.get("AI_MODEL", "deepseek-chat")

    # Endpoint transkrypcji (etap 4)
    INGEST_TOKEN = _secret("INGEST_TOKEN")

    # Zadania w tle
    SCHEDULER_ENABLED = os.environ.get("SCHEDULER_ENABLED", "1") == "1"

    # Rate limiting
    RATELIMIT_STORAGE_URI = "memory://"
    RATELIMIT_HEADERS_ENABLED = True


class DevConfig(Config):
    DEBUG = True
    # Bez HTTPS na localhoście ciasteczko z flagą Secure nigdy nie dotrze
    SESSION_COOKIE_SECURE = False
    REMEMBER_COOKIE_SECURE = False
    SQLALCHEMY_DATABASE_URI = _database_url() or (
        "postgresql+psycopg://postgres:postgres@localhost:5432/noxso_crm"
    )
    SECRET_KEY = os.environ.get("SECRET_KEY", "dev-only-nie-uzywaj-na-produkcji")


class TestConfig(Config):
    TESTING = True
    WTF_CSRF_ENABLED = False
    SCHEDULER_ENABLED = False
    # Limiter trzyma liczniki w pamięci procesu, a testy dzielą jedną aplikację.
    # Włączony odciąłby logowanie po piątym teście, który się loguje — i to nie
    # dlatego, że coś jest zepsute. Sam limit sprawdzamy ręcznie, na żywej aplikacji.
    RATELIMIT_ENABLED = False
    SESSION_COOKIE_SECURE = False
    SECRET_KEY = "test"
    SQLALCHEMY_DATABASE_URI = os.environ.get(
        "TEST_DATABASE_URL",
        "postgresql+psycopg://postgres:postgres@localhost:5432/noxso_crm_test",
    )


class ProdConfig(Config):
    DEBUG = False


CONFIGS = {"development": DevConfig, "testing": TestConfig, "production": ProdConfig}


def get_config(name: str | None = None) -> type[Config]:
    # Wyrażenie warunkowe, nie `or` — przy `or` mypy zostawia typ `str | None`.
    resolved = name if name else os.environ.get("FLASK_ENV", "development")
    return CONFIGS.get(resolved, DevConfig)
