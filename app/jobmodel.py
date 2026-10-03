from __future__ import annotations

from dataclasses import asdict, dataclass, field
from typing import Optional


@dataclass
class Job:
    """Normalized job posting shared by every source."""
    id: str
    title: str
    company: str = ""
    location: str = ""
    url: str = ""
    posted: str = ""
    description: str = ""
    seniority: str = ""
    employment_type: str = ""
    extra: dict = field(default_factory=dict)
    source: str = "linkedin"
    sources: list = field(default_factory=list)
    remote: Optional[bool] = None
    salary: str = ""
    tags: list = field(default_factory=list)

    def to_dict(self) -> dict:
        d = asdict(self)
        d["description_missing"] = len(self.description) < 80
        if not d["sources"]:
            d["sources"] = [self.source]
        return d
