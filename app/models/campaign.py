"""Kampanie SMS (etap 7)."""

from __future__ import annotations

from datetime import datetime
from typing import TYPE_CHECKING, Any

import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.extensions import db
from app.models.enums import BatchStatus, CampaignStatus, RecipientStatus

if TYPE_CHECKING:
    from app.models.client import Client


class Campaign(db.Model):
    __tablename__ = "campaigns"

    id: Mapped[int] = mapped_column(primary_key=True)
    name: Mapped[str] = mapped_column(sa.String(200), nullable=False)

    # Treść z placeholderami w konwencji interfejsu: {{name}}, {{city}}.
    # Tłumaczeniem na [%param1%] dostawcy zajmuje się adapter.
    message: Mapped[str] = mapped_column(sa.Text, nullable=False)

    status: Mapped[CampaignStatus] = mapped_column(
        sa.Enum(CampaignStatus, native_enum=False, length=16),
        nullable=False,
        default=CampaignStatus.DRAFT,
        server_default=CampaignStatus.DRAFT.value,
        index=True,
    )
    clear_polish: Mapped[bool] = mapped_column(
        sa.Boolean, nullable=False, default=False, server_default=sa.false()
    )

    scheduled_at: Mapped[datetime | None] = mapped_column(sa.DateTime(timezone=True))
    sent_at: Mapped[datetime | None] = mapped_column(sa.DateTime(timezone=True))
    tested_at: Mapped[datetime | None] = mapped_column(sa.DateTime(timezone=True))
    test_report: Mapped[dict[str, Any] | None] = mapped_column(JSONB)

    created_at: Mapped[datetime] = mapped_column(
        sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()
    )

    batches: Mapped[list[CampaignBatch]] = relationship(
        back_populates="campaign", cascade="all, delete-orphan"
    )
    recipients: Mapped[list[CampaignRecipient]] = relationship(
        back_populates="campaign", cascade="all, delete-orphan"
    )

    def __repr__(self) -> str:
        return f"<Campaign {self.id} {self.name!r}>"


class CampaignBatch(db.Model):
    """Jedno żądanie do API dostawcy = jedna paczka."""

    __tablename__ = "campaign_batches"

    id: Mapped[int] = mapped_column(primary_key=True)
    campaign_id: Mapped[int] = mapped_column(
        sa.ForeignKey("campaigns.id", ondelete="CASCADE"), nullable=False, index=True
    )

    provider_id: Mapped[str | None] = mapped_column(sa.String(64), index=True)

    # messageId zaczynający się od "B-" oznacza bufor kolejkowy dostawcy —
    # takiej wysyłki nie da się anulować, więc przycisk anulowania znika z UI.
    buffered: Mapped[bool] = mapped_column(
        sa.Boolean, nullable=False, default=False, server_default=sa.false()
    )

    recipient_count: Mapped[int] = mapped_column(
        sa.Integer, nullable=False, default=0, server_default="0"
    )
    status: Mapped[BatchStatus] = mapped_column(
        sa.Enum(BatchStatus, native_enum=False, length=16),
        nullable=False,
        default=BatchStatus.PENDING,
        server_default=BatchStatus.PENDING.value,
    )
    error_code: Mapped[int | None] = mapped_column(sa.Integer)
    error_message: Mapped[str | None] = mapped_column(sa.Text)
    sent_at: Mapped[datetime | None] = mapped_column(sa.DateTime(timezone=True))

    campaign: Mapped[Campaign] = relationship(back_populates="batches")

    def __repr__(self) -> str:
        return f"<CampaignBatch {self.id} provider={self.provider_id}>"


class CampaignRecipient(db.Model):
    __tablename__ = "campaign_recipients"

    id: Mapped[int] = mapped_column(primary_key=True)
    campaign_id: Mapped[int] = mapped_column(
        sa.ForeignKey("campaigns.id", ondelete="CASCADE"), nullable=False
    )
    client_id: Mapped[int | None] = mapped_column(
        sa.ForeignKey("clients.id", ondelete="SET NULL")
    )

    phone_e164: Mapped[str] = mapped_column(sa.String(20), nullable=False, index=True)
    rendered_text: Mapped[str] = mapped_column(sa.Text, nullable=False)

    status: Mapped[RecipientStatus] = mapped_column(
        sa.Enum(RecipientStatus, native_enum=False, length=16),
        nullable=False,
        default=RecipientStatus.PENDING,
        server_default=RecipientStatus.PENDING.value,
    )
    parts: Mapped[int | None] = mapped_column(sa.Integer)
    delivered_at: Mapped[datetime | None] = mapped_column(sa.DateTime(timezone=True))
    delivery_error: Mapped[str | None] = mapped_column(sa.String(255))
    sent_at: Mapped[datetime | None] = mapped_column(sa.DateTime(timezone=True))

    campaign: Mapped[Campaign] = relationship(back_populates="recipients")
    client: Mapped[Client | None] = relationship()

    __table_args__ = (
        sa.Index("ix_campaign_recipients_campaign_status", "campaign_id", "status"),
    )

    def __repr__(self) -> str:
        return f"<CampaignRecipient {self.phone_e164} {self.status.value}>"
