from __future__ import annotations

from dataclasses import asdict, dataclass, field, fields


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

    def to_dict(self) -> dict:
        return {**asdict(self), "key": self.key}

    @classmethod
    def from_dict(cls, data: dict) -> Game:
        known = {f.name for f in fields(cls)}
        return cls(**{k: v for k, v in data.items() if k in known})
