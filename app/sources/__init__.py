"""Job source registry."""
from __future__ import annotations

from . import adzuna, ats, boards, linkedin_src, urlimport
from .base import JobQuery, Source, SourceError

ALL: list[Source] = [*linkedin_src.SOURCES, *boards.SOURCES, *ats.SOURCES, *adzuna.SOURCES, *urlimport.SOURCES]
BY_ID: dict[str, Source] = {s.id: s for s in ALL}

__all__ = ["ALL", "BY_ID", "JobQuery", "Source", "SourceError"]
