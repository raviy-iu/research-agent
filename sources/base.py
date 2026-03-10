"""
sources/base.py – Shared data models and abstract base class.
"""
from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from query_builder import QueryBundle


@dataclass
class Article:
    """Represents a single research article."""

    title: str
    source: str       # Display name: "IEEE", "ScienceDirect", "MDPI", "Medium", etc.
    url: str          # Direct link to view / download the article
    doi: str = ""     # Used for cross-source deduplication
    abstract: str = ""
    year: int | None = None
    authors: list[str] = field(default_factory=list)

    def dedup_key(self) -> str:
        """Return a normalised key for deduplication (DOI preferred, else URL)."""
        if self.doi:
            return self.doi.lower().strip()
        return self.url.lower().strip()

    def to_dict(self) -> dict:
        return {
            "title": self.title,
            "source": self.source,
            "url": self.url,
            "doi": self.doi,
            "abstract": self.abstract,
            "year": self.year,
            "authors": self.authors,
        }


class BaseSource(ABC):
    """Abstract base class that every source must implement."""

    @abstractmethod
    async def fetch(self, query: "QueryBundle") -> list[Article]:
        """Fetch articles matching *query* and return them as Article objects."""
        ...
