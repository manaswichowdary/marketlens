"""The one shape every source is turned into, so later steps do not care where a posting came from."""
from dataclasses import dataclass, asdict


@dataclass
class Posting:
    source: str            # "adzuna" or "remotive"
    source_id: str         # the id that source uses
    title: str
    company: str
    location: str
    description: str
    posted_at: str         # ISO date text, as the source gave it
    url: str
    category: str
    salary_min: float | None
    salary_max: float | None
    fetched_at: str        # when we pulled it

    def as_dict(self):
        return asdict(self)
