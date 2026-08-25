"""Wydarzenia kalendarza (etap 6)."""

from __future__ import annotations

from datetime import datetime
from typing import TYPE_CHECKING

import sqlalchemy as sa
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.extensions import db
from app.models.enums import EventSource

if TYPE_CHECKING:
    from app.models.client import Client
    from app.models.transcript import Transcript


class CalendarEvent(db.Model):
    __tablename__ = "calendar_events"

    id: Mapped[int] = mapped_column(primary_key=True)
    client_id: Mapped[int | None] = mapped_column(
        sa.ForeignKey("clients.id", ondelete="CASCADE"), index=True
    )
    transcript_id: Mapped[int | None] = mapped_column(
        sa.ForeignKey("transcripts.id", ondelete="SET NULL")
    )

    title: Mapped[str] = mapped_column(sa.String(300), nullable=False)
    description: Mapped[str | None] = mapped_column(sa.Text)

    starts_at: Mapped[datetime] = mapped_column(
        sa.DateTime(timezone=True), nullable=False, index=True
    )
    ends_at: Mapped[datetime | None] = mapped_column(sa.DateTime(timezone=True))
    all_day: Mapped[bool] = mapped_column(
        sa.Boolean, nullable=False, default=False, server_default=sa.false()
    )

    source: Mapped[EventSource] = mapped_column(
        sa.Enum(EventSource, native_enum=False, length=16),
        nullable=False,
        default=EventSource.MANUAL,
        server_default=EventSource.MANUAL.value,
    )
    # Pewność modelu: high / medium / low. Tylko dla source=AI.
    confidence: Mapped[str | None] = mapped_column(sa.String(16))

    # Wydarzenia z AI NIGDY nie powstają jako potwierdzone (sekcja 9 specyfikacji).
    confirmed: Mapped[bool] = mapped_column(
        sa.Boolean, nullable=False, default=False, server_default=sa.false()
    )

    created_at: Mapped[datetime] = mapped_column(
        sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()
    )

    client: Mapped[Client | None] = relationship(back_populates="events")
    transcript: Mapped[Transcript | None] = relationship(back_populates="events")

    def __repr__(self) -> str:
        return f"<CalendarEvent {self.id} {self.title!r}>"
