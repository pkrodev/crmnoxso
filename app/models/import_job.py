"""Zadanie importu arkusza.

Postęp trzymamy w bazie, a nie w pamięci procesu — dzięki temu pasek postępu
działa również po restarcie aplikacji, a historia importów zostaje.
"""

from __future__ import annotations

from datetime import datetime
from typing import Any

import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from app.extensions import db
from app.models.enums import ImportStatus


class ImportJob(db.Model):
    __tablename__ = "import_jobs"

    id: Mapped[int] = mapped_column(primary_key=True)

    filename: Mapped[str] = mapped_column(sa.String(255), nullable=False)
    stored_path: Mapped[str] = mapped_column(sa.String(500), nullable=False)

    status: Mapped[ImportStatus] = mapped_column(
        sa.Enum(ImportStatus, native_enum=False, length=16),
        nullable=False,
        default=ImportStatus.PENDING,
        server_default=ImportStatus.PENDING.value,
        index=True,
    )

    total: Mapped[int] = mapped_column(
        sa.Integer, nullable=False, default=0, server_default="0"
    )
    processed: Mapped[int] = mapped_column(
        sa.Integer, nullable=False, default=0, server_default="0"
    )

    created: Mapped[int] = mapped_column(
        sa.Integer, nullable=False, default=0, server_default="0"
    )
    updated: Mapped[int] = mapped_column(
        sa.Integer, nullable=False, default=0, server_default="0"
    )
    skipped: Mapped[int] = mapped_column(
        sa.Integer, nullable=False, default=0, server_default="0"
    )
    flagged: Mapped[int] = mapped_column(
        sa.Integer, nullable=False, default=0, server_default="0"
    )

    report: Mapped[dict[str, Any] | None] = mapped_column(JSONB)
    error: Mapped[str | None] = mapped_column(sa.Text)

    created_at: Mapped[datetime] = mapped_column(
        sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()
    )
    finished_at: Mapped[datetime | None] = mapped_column(sa.DateTime(timezone=True))

    @property
    def percent(self) -> int:
        if not self.total:
            return 0
        return min(100, round(self.processed * 100 / self.total))

    def __repr__(self) -> str:
        return f"<ImportJob {self.id} {self.filename!r} {self.status.value}>"
