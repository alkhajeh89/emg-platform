"""Shared pagination conventions."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Generic, TypeVar

T = TypeVar("T")

DEFAULT_PAGE_SIZE = 50
MAX_PAGE_SIZE = 200


@dataclass(frozen=True)
class PaginationParams:
    page: int = 1
    page_size: int = DEFAULT_PAGE_SIZE

    def __post_init__(self) -> None:
        if self.page < 1:
            raise ValueError("page must be >= 1")
        if not (1 <= self.page_size <= MAX_PAGE_SIZE):
            raise ValueError(f"page_size must be between 1 and {MAX_PAGE_SIZE}")


@dataclass(frozen=True)
class PaginatedResponse(Generic[T]):
    items: list[T]
    page: int
    page_size: int
    total_items: int

    @property
    def total_pages(self) -> int:
        if self.page_size == 0:
            return 0
        return (self.total_items + self.page_size - 1) // self.page_size
