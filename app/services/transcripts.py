"""Lista rozmów — filtrowanie i liczniki zakładek.

Ta sama zasada, co przy klientach: zapytania mieszkają w serwisie, widok tylko
je woła. Dzięki temu da się je przetestować bez klienta HTTP, a etap 5 (analiza
AI) i etap 6 (kalendarz) będą sięgać po te same funkcje.
"""

from __future__ import annotations

import re
from dataclasses import dataclass

import sqlalchemy as sa
from sqlalchemy.orm import selectinload

from app.extensions import db
from app.models import Client, Transcript, TranscriptStatus
from app.services.paging import PAGE_SIZE, Page

# Pseudo-status zakładki „Wymagają uwagi". Nie jest wartością z bazy — łączy
# dwa realne stany: rozmowy bez klienta (NEEDS_REVIEW) i te, na których
# przetwarzanie się wyłożyło (FAILED). Specyfikacja wymaga jednej zakładki
# na obie te sytuacje, bo dla użytkownika znaczą to samo: „zajmij się tym".
ATTENTION = "uwaga"

ATTENTION_STATUSES = (TranscriptStatus.NEEDS_REVIEW, TranscriptStatus.FAILED)

MIN_DIGITS = 4


@dataclass(slots=True)
class TranscriptFilters:
    query: str = ""
    status: str = ""
    page: int = 1

    @classmethod
    def from_request(cls, args) -> TranscriptFilters:
        try:
            page = max(1, int(args.get("strona", 1)))
        except (TypeError, ValueError):
            page = 1
        status = (args.get("status") or "").strip()
        allowed = {s.value for s in TranscriptStatus} | {ATTENTION}
        return cls(
            query=(args.get("q") or "").strip(),
            status=status if status in allowed else "",
            page=page,
        )

    @property
    def active(self) -> bool:
        return bool(self.query or self.status)

    def as_params(self) -> dict[str, str]:
        params: dict[str, str] = {}
        if self.query:
            params["q"] = self.query
        if self.status:
            params["status"] = self.status
        return params


def build_query(filters: TranscriptFilters):
    stmt = sa.select(Transcript).outerjoin(Client, Transcript.client_id == Client.id)

    if filters.status == ATTENTION:
        stmt = stmt.where(Transcript.status.in_(ATTENTION_STATUSES))
    elif filters.status:
        stmt = stmt.where(Transcript.status == TranscriptStatus(filters.status))

    term = filters.query
    if term:
        like = f"%{term}%"
        clauses = [
            Transcript.raw_text.ilike(like),
            Transcript.ai_summary.ilike(like),
            Transcript.source_file.ilike(like),
            Client.name.ilike(like),
        ]
        # Numer wpisany w dowolnym zapisie — te same warianty, co w wyszukiwarce
        # klientów. Porównujemy same cyfry, więc „601-092-947" trafia w E.164.
        digits = re.sub(r"\D", "", term)
        if len(digits) >= MIN_DIGITS:
            clauses.append(
                sa.func.regexp_replace(
                    sa.func.coalesce(Transcript.phone_e164, ""), r"\D", "", "g"
                ).like(f"%{digits}%")
            )
        stmt = stmt.where(sa.or_(*clauses))

    return stmt


def list_transcripts(filters: TranscriptFilters) -> Page[Transcript]:
    stmt = build_query(filters)

    total = db.session.scalar(
        sa.select(sa.func.count()).select_from(stmt.order_by(None).subquery())
    )

    rows = db.session.scalars(
        stmt.options(selectinload(Transcript.client))
        .order_by(Transcript.created_at.desc(), Transcript.id.desc())
        .limit(PAGE_SIZE)
        .offset((filters.page - 1) * PAGE_SIZE)
    ).all()

    return Page(rows=list(rows), total=total or 0, page=filters.page)


def status_counts() -> dict[str, int]:
    """Liczniki do zakładek: ile rozmów w każdym stanie plus „wymagają uwagi"."""
    rows = db.session.execute(
        sa.select(Transcript.status, sa.func.count())
        .select_from(Transcript)
        .group_by(Transcript.status)
    ).all()

    counts = {status.value: 0 for status in TranscriptStatus}
    for status, count in rows:
        counts[status.value] = count

    counts["total"] = sum(counts[s.value] for s in TranscriptStatus)
    counts[ATTENTION] = sum(counts[s.value] for s in ATTENTION_STATUSES)
    return counts
