"""Transkrypcje rozmów telefonicznych (etapy 4–5)."""

from __future__ import annotations

from datetime import date, datetime
from typing import TYPE_CHECKING, Any

import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.extensions import db
from app.models.enums import TranscriptStatus

if TYPE_CHECKING:
    from app.models.calendar_event import CalendarEvent
    from app.models.client import Client


class Transcript(db.Model):
    __tablename__ = "transcripts"

    id: Mapped[int] = mapped_column(primary_key=True)
    client_id: Mapped[int | None] = mapped_column(
        sa.ForeignKey("clients.id", ondelete="SET NULL"), index=True
    )

    # Surowy tekst zostaje zawsze — także gdy analiza AI zawiodła.
    raw_text: Mapped[str] = mapped_column(sa.Text, nullable=False)

    phone_raw: Mapped[str | None] = mapped_column(sa.String(120))
    phone_e164: Mapped[str | None] = mapped_column(sa.String(20), index=True)
    call_date: Mapped[date | None] = mapped_column(sa.Date)

    status: Mapped[TranscriptStatus] = mapped_column(
        sa.Enum(TranscriptStatus, native_enum=False, length=16),
        nullable=False,
        default=TranscriptStatus.PENDING,
        server_default=TranscriptStatus.PENDING.value,
        index=True,
    )

    ai_summary: Mapped[str | None] = mapped_column(sa.Text)
    ai_sentiment: Mapped[str | None] = mapped_column(sa.String(16))
    ai_outcome: Mapped[str | None] = mapped_column(sa.String(64))
    ai_raw: Mapped[dict[str, Any] | None] = mapped_column(JSONB)
    tokens_used: Mapped[int | None] = mapped_column(sa.Integer)

    error: Mapped[str | None] = mapped_column(sa.Text)
    source_file: Mapped[str | None] = mapped_column(sa.String(255))
    attempts: Mapped[int] = mapped_column(
        sa.Integer, nullable=False, default=0, server_default="0"
    )

    # Od kiedy wolno podjąć kolejną próbę analizy.
    #
    # Specyfikacja wymaga trzech prób z ROSNĄCYM odstępem, a zadanie w tle chodzi
    # co 30 sekund. Bez zapisania tego momentu w bazie trzy próby spaliłyby się
    # w półtorej minuty — czyli dokładnie wtedy, gdy dostawca modelu ma chwilową
    # awarię i warto poczekać. Trzymanie odstępu w pamięci procesu też nie
    # wchodzi w grę: restart aplikacji kasowałby go do zera.
    next_attempt_at: Mapped[datetime | None] = mapped_column(sa.DateTime(timezone=True))

    created_at: Mapped[datetime] = mapped_column(
        sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()
    )
    processed_at: Mapped[datetime | None] = mapped_column(sa.DateTime(timezone=True))

    client: Mapped[Client | None] = relationship(back_populates="transcripts")
    events: Mapped[list[CalendarEvent]] = relationship(back_populates="transcript")

    def __repr__(self) -> str:
        return f"<Transcript {self.id} {self.status.value}>"
