"""Oś czasu klienta.

To wymóg funkcjonalny, nie log techniczny — użytkownik ma w jednym miejscu widzieć
całą historię kontaktu z klientem.
"""

from __future__ import annotations

from datetime import datetime
from typing import TYPE_CHECKING, Any

import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.extensions import db
from app.models.enums import ActivityActor, ActivityType

if TYPE_CHECKING:
    from app.models.client import Client


class Activity(db.Model):
    __tablename__ = "activities"

    id: Mapped[int] = mapped_column(primary_key=True)
    client_id: Mapped[int] = mapped_column(
        sa.ForeignKey("clients.id", ondelete="CASCADE"), nullable=False
    )

    type: Mapped[ActivityType] = mapped_column(
        sa.Enum(ActivityType, native_enum=False, length=32), nullable=False, index=True
    )
    title: Mapped[str] = mapped_column(sa.String(300), nullable=False)
    description: Mapped[str | None] = mapped_column(sa.Text)

    # Szczegóły zależne od typu, np. {"field": "email", "from": "x", "to": "y"}
    meta: Mapped[dict[str, Any] | None] = mapped_column(JSONB)

    actor: Mapped[ActivityActor] = mapped_column(
        sa.Enum(ActivityActor, native_enum=False, length=16),
        nullable=False,
        default=ActivityActor.USER,
        server_default=ActivityActor.USER.value,
    )
    occurred_at: Mapped[datetime] = mapped_column(
        sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()
    )

    client: Mapped[Client] = relationship(back_populates="activities")

    __table_args__ = (
        sa.Index("ix_activities_client_occurred", "client_id", "occurred_at"),
    )

    def __repr__(self) -> str:
        return f"<Activity {self.type.value} client={self.client_id}>"
