"""Wspólne narzędzia testów."""

from __future__ import annotations

import os
from pathlib import Path

import pytest

os.environ.setdefault("FLASK_ENV", "testing")
os.environ.setdefault("ADMIN_LOGIN", "Milosz")
# Hash hasła "testowe-haslo-123" — tylko na potrzeby testów.
os.environ.setdefault(
    "ADMIN_PASSWORD_HASH",
    "$2b$12$LQv3c1yqBWVHxkd0LHAkCOYz6TtxMQJqhN8/LewKyF9aQ2Zx3nGJa",
)

PROJECT_ROOT = Path(__file__).resolve().parent.parent


@pytest.fixture(scope="session")
def app():
    """Aplikacja w konfiguracji testowej, z czystym schematem bazy."""
    from app import create_app
    from app.extensions import db

    application = create_app("testing")

    with application.app_context():
        try:
            db.drop_all()
            db.create_all()
        except Exception as exc:  # noqa: BLE001
            pytest.skip(f"Brak połączenia z bazą testową: {exc}")

    yield application

    with application.app_context():
        db.session.remove()
        db.drop_all()


@pytest.fixture
def session(app):
    """Czysta baza przed każdym testem korzystającym z bazy."""
    from app.extensions import db

    with app.app_context():
        for table in reversed(db.metadata.sorted_tables):
            db.session.execute(table.delete())
        db.session.commit()
        yield db.session
        db.session.rollback()
        db.session.remove()


@pytest.fixture
def client(app):
    return app.test_client()


def make_sheet(path: Path, rows: list[list[str | None]], *, title_row: bool = True):
    """Buduje arkusz .xlsx o strukturze takiej jak plik produkcyjny.

    Pierwszy wiersz to tytuł, drugi to nagłówki, dane od trzeciego.
    """
    from openpyxl import Workbook

    workbook = Workbook()
    sheet = workbook.active
    sheet.title = "2100"

    if title_row:
        sheet.append(["Zawartość grupy kontrahentów"])
    for row in rows:
        sheet.append(row)

    workbook.save(path)
    return path
