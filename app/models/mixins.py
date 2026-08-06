"""Wspólne elementy modeli."""

from __future__ import annotations

from datetime import datetime

import sqlalchemy as sa
from sqlalchemy.orm import Mapped, mapped_column


def utc_now_column(onupdate: bool = False) -> Mapped[datetime]:
    """Kolumna znacznika czasu w UTC, wypełniana przez bazę."""
    return mapped_column(
        sa.DateTime(timezone=True),
        nullable=False,
        server_default=sa.func.now(),
        onupdate=sa.func.now() if onupdate else None,
    )


class TimestampMixin:
    """Para kolumn ``created_at`` / ``updated_at``.

    Wszystkie daty w bazie są w UTC (sekcja 12 specyfikacji); przeliczanie na
    ``Europe/Warsaw`` odbywa się dopiero w szablonach.
    """

    created_at: Mapped[datetime] = mapped_column(
        sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()
    )
    updated_at: Mapped[datetime] = mapped_column(
        sa.DateTime(timezone=True),
        nullable=False,
        server_default=sa.func.now(),
        onupdate=sa.func.now(),
    )
