"""Notatki przy kliencie."""

from __future__ import annotations

from typing import TYPE_CHECKING

import sqlalchemy as sa
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.extensions import db
from app.models.mixins import TimestampMixin

if TYPE_CHECKING:
    from app.models.client import Client


class Note(TimestampMixin, db.Model):
    __tablename__ = "notes"

    id: Mapped[int] = mapped_column(primary_key=True)
    client_id: Mapped[int] = mapped_column(
        sa.ForeignKey("clients.id", ondelete="CASCADE"), nullable=False
    )
    body: Mapped[str] = mapped_column(sa.Text, nullable=False)
    pinned: Mapped[bool] = mapped_column(
        sa.Boolean, nullable=False, default=False, server_default=sa.false()
    )

    client: Mapped[Client] = relationship(back_populates="notes")

    __table_args__ = (sa.Index("ix_notes_client_created", "client_id", "created_at"),)

    def __repr__(self) -> str:
        return f"<Note {self.id} client={self.client_id}>"
