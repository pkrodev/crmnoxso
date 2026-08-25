"""Klient, jego numery telefonu i tagi."""

from __future__ import annotations

from datetime import datetime
from typing import TYPE_CHECKING

import sqlalchemy as sa
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.extensions import db
from app.models.enums import ClientSource, ClientStatus
from app.models.mixins import TimestampMixin

if TYPE_CHECKING:
    from app.models.activity import Activity
    from app.models.calendar_event import CalendarEvent
    from app.models.note import Note
    from app.models.transcript import Transcript


client_tags = sa.Table(
    "client_tags",
    db.metadata,
    sa.Column(
        "client_id",
        sa.Integer,
        sa.ForeignKey("clients.id", ondelete="CASCADE"),
        primary_key=True,
    ),
    sa.Column(
        "tag_id",
        sa.Integer,
        sa.ForeignKey("tags.id", ondelete="CASCADE"),
        primary_key=True,
    ),
)


class Client(TimestampMixin, db.Model):
    __tablename__ = "clients"

    id: Mapped[int] = mapped_column(primary_key=True)

    # Akronim z arkusza księgowego — ZAWSZE string, wiodące zera mają znaczenie
    # ("0156" to inny klient niż 156). To jedyny w pełni unikalny klucz w danych
    # źródłowych, więc na nim opiera się automatyczna deduplikacja importu.
    acronym: Mapped[str | None] = mapped_column(sa.String(32), unique=True, index=True)

    name: Mapped[str] = mapped_column(sa.String(300), nullable=False, index=True)

    nip: Mapped[str | None] = mapped_column(sa.String(16), index=True)
    nip_valid: Mapped[bool] = mapped_column(
        sa.Boolean, nullable=False, default=False, server_default=sa.false()
    )

    city: Mapped[str | None] = mapped_column(sa.String(160), index=True)
    postal_code: Mapped[str | None] = mapped_column(sa.String(16))
    street: Mapped[str | None] = mapped_column(sa.String(300))
    email: Mapped[str | None] = mapped_column(sa.String(255), index=True)

    source: Mapped[ClientSource] = mapped_column(
        sa.Enum(ClientSource, native_enum=False, length=16),
        nullable=False,
        default=ClientSource.MANUAL,
        server_default=ClientSource.MANUAL.value,
    )
    status: Mapped[ClientStatus] = mapped_column(
        sa.Enum(ClientStatus, native_enum=False, length=16),
        nullable=False,
        default=ClientStatus.ACTIVE,
        server_default=ClientStatus.ACTIVE.value,
        index=True,
    )

    # Zgoda na SMS marketingowy — kreator kampanii domyślnie filtruje po tym polu
    # (Prawo komunikacji elektronicznej, sekcja 8 specyfikacji).
    sms_consent: Mapped[bool] = mapped_column(
        sa.Boolean, nullable=False, default=False, server_default=sa.false()
    )
    sms_consent_at: Mapped[datetime | None] = mapped_column(sa.DateTime(timezone=True))

    phones: Mapped[list[Phone]] = relationship(
        back_populates="client",
        cascade="all, delete-orphan",
        order_by="Phone.is_primary.desc(), Phone.id",
        lazy="selectin",
    )
    notes: Mapped[list[Note]] = relationship(
        back_populates="client", cascade="all, delete-orphan"
    )
    activities: Mapped[list[Activity]] = relationship(
        back_populates="client", cascade="all, delete-orphan"
    )
    transcripts: Mapped[list[Transcript]] = relationship(back_populates="client")
    events: Mapped[list[CalendarEvent]] = relationship(back_populates="client")
    tags: Mapped[list[Tag]] = relationship(
        secondary=client_tags, back_populates="clients", lazy="selectin"
    )

    __table_args__ = (sa.Index("ix_clients_name_city", "name", "city"),)

    @property
    def primary_phone(self) -> Phone | None:
        for phone in self.phones:
            if phone.is_primary:
                return phone
        return self.phones[0] if self.phones else None

    def has_tag(self, name: str) -> bool:
        return any(tag.name == name for tag in self.tags)

    def __repr__(self) -> str:
        return f"<Client {self.acronym or self.id} {self.name!r}>"


class Phone(db.Model):
    """Numer telefonu klienta.

    Osobna tabela, bo w arkuszu zdarzają się dwa numery w jednej komórce,
    a klient bywa osiągalny pod komórką i stacjonarnym jednocześnie.
    """

    __tablename__ = "phones"

    id: Mapped[int] = mapped_column(primary_key=True)
    client_id: Mapped[int] = mapped_column(
        sa.ForeignKey("clients.id", ondelete="CASCADE"), nullable=False, index=True
    )

    # UWAGA: indeks bez ograniczenia UNIQUE. W bazie źródłowej 58 numerów należy
    # do dwóch lub trzech różnych klientów (gospodarstwa rodzinne pod jednym
    # numerem). Wymuszenie unikalności odrzuciłoby te rekordy przy imporcie.
    # Kosztem jest wieloznaczność przy dopasowaniu transkrypcji — rozstrzygana
    # ręcznie przez status NEEDS_REVIEW (etap 4).
    e164: Mapped[str | None] = mapped_column(sa.String(20), index=True)

    # Oryginał z importu — zostaje zawsze, także gdy numeru nie dało się sparsować.
    raw: Mapped[str | None] = mapped_column(sa.String(120))

    is_primary: Mapped[bool] = mapped_column(
        sa.Boolean, nullable=False, default=False, server_default=sa.false()
    )
    label: Mapped[str | None] = mapped_column(sa.String(40))

    client: Mapped[Client] = relationship(back_populates="phones")

    def __repr__(self) -> str:
        return f"<Phone {self.e164 or self.raw!r}>"


class Tag(db.Model):
    __tablename__ = "tags"

    id: Mapped[int] = mapped_column(primary_key=True)
    name: Mapped[str] = mapped_column(sa.String(64), nullable=False, unique=True)
    color: Mapped[str | None] = mapped_column(sa.String(16))

    clients: Mapped[list[Client]] = relationship(
        secondary=client_tags, back_populates="tags"
    )

    def __repr__(self) -> str:
        return f"<Tag {self.name!r}>"


# Tagi zakładane automatycznie przez import — nazwy bez polskich znaków,
# żeby dało się ich używać w adresach URL filtrów bez kodowania.
TAG_NEEDS_REVIEW = "do-weryfikacji"
TAG_POSSIBLE_DUPLICATE = "mozliwy-duplikat"
TAG_FROM_TRANSCRIPT = "nowy-z-rozmowy"

SYSTEM_TAGS = {
    TAG_NEEDS_REVIEW: "#EA580C",
    TAG_POSSIBLE_DUPLICATE: "#B91C1C",
    TAG_FROM_TRANSCRIPT: "#15803D",
}
