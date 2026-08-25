"""Testy czyszczenia sekretów z otoczenia.

Powstały po konkretnej wpadce na produkcji: hash hasła wjechał do panelu
hostingu z doklejonym BOM-em (``﻿``), więc miał 61 znaków zamiast 60.
``bcrypt.checkpw`` uznał go za nieprawidłową sól i odrzucał każde hasło,
a aplikacja mówiła tylko „nieprawidłowy login lub hasło" — bo celowo nie
zdradza, która część zawiodła. Diagnoza zajęła więcej czasu niż napisanie
tej funkcji.
"""

from __future__ import annotations

import pytest

from app.config import _secret

BOM = "﻿"


@pytest.mark.parametrize(
    "given",
    [
        "$2b$12$abcdefghijklmnopqrstuv",
        BOM + "$2b$12$abcdefghijklmnopqrstuv",
        "$2b$12$abcdefghijklmnopqrstuv\n",
        "  $2b$12$abcdefghijklmnopqrstuv  ",
        BOM + "$2b$12$abcdefghijklmnopqrstuv\r\n",
    ],
)
def test_invisible_characters_are_stripped(monkeypatch, given):
    monkeypatch.setenv("TESTOWY_SEKRET", given)
    assert _secret("TESTOWY_SEKRET") == "$2b$12$abcdefghijklmnopqrstuv"


def test_missing_variable_gives_the_default(monkeypatch):
    monkeypatch.delenv("TESTOWY_SEKRET", raising=False)
    assert _secret("TESTOWY_SEKRET") == ""
    assert _secret("TESTOWY_SEKRET", "zapasowa") == "zapasowa"


def test_value_of_only_whitespace_counts_as_empty(monkeypatch):
    """Pusty token musi znaczyć „wyłączone", a nie „wpuszczaj wszystkich"."""
    monkeypatch.setenv("TESTOWY_SEKRET", f"  {BOM}\n ")
    assert _secret("TESTOWY_SEKRET") == ""
