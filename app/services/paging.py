"""Stronicowanie po stronie serwera.

Wspólne dla listy klientów i listy rozmów — obie pokazują ten sam pasek
„1–50 z 1923" i te same przyciski, więc liczenie stron mieszka w jednym miejscu.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Generic, TypeVar

T = TypeVar("T")

PAGE_SIZE = 50


@dataclass(slots=True)
class Page(Generic[T]):
    rows: list[T] = field(default_factory=list)
    total: int = 0
    page: int = 1
    page_size: int = PAGE_SIZE

    @property
    def pages(self) -> int:
        return max(1, -(-self.total // self.page_size))

    @property
    def has_prev(self) -> bool:
        return self.page > 1

    @property
    def has_next(self) -> bool:
        return self.page < self.pages

    @property
    def first_index(self) -> int:
        return 0 if not self.total else (self.page - 1) * self.page_size + 1

    @property
    def last_index(self) -> int:
        return min(self.page * self.page_size, self.total)
