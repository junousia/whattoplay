from __future__ import annotations

import re
from dataclasses import asdict, dataclass, field, fields


def normalize_name(name: str) -> str:
    """Same game on different stores (and PS4/PS5 editions) share this key."""
    return re.sub(r"[^a-z0-9]+", " ", name.lower()).strip()


@dataclass
class Game:
    name: str
    platform: str
    external_id: str
    playtime_minutes: int | None = None  # None = the store exposes no playtime, not "never played"
    genres: list[str] = field(default_factory=list)
    metacritic_score: int | None = None
    metacritic_url: str | None = None
    header_image_url: str | None = None
    store_url: str | None = None

    @property
    def key(self) -> str:
        return f"{self.platform}:{self.external_id}"

    @property
    def group(self) -> str:
        return normalize_name(self.name)

    def to_dict(self) -> dict:
        return {**asdict(self), "key": self.key}

    @classmethod
    def from_dict(cls, data: dict) -> Game:
        known = {f.name for f in fields(cls)}
        return cls(**{k: v for k, v in data.items() if k in known})
