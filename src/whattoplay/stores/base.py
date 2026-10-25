"""The store backend interface. Subclass `Store` to add a platform (PSN, GOG, Xbox, ...)."""

from __future__ import annotations

from collections.abc import Callable, Mapping
from dataclasses import dataclass

from whattoplay.models import Game


class StoreError(RuntimeError):
    """The store failed while fetching (network error, bad credentials, private profile)."""


@dataclass(frozen=True)
class Setting:
    """One configuration value a store needs.

    Resolved from the environment variable `env` first, then (non-secret values only)
    from `[stores.<name>]` in config.toml. Secrets live only in the environment / `.env`.
    """

    key: str
    env: str
    prompt: str
    secret: bool = False
    required: bool = True


class Store:
    name: str = ""
    label: str = ""
    settings: tuple[Setting, ...] = ()

    def __init__(self, config: Mapping[str, object], env: Mapping[str, str]):
        self.config = config
        self.env = env

    def value(self, key: str) -> str | None:
        setting = next(s for s in self.settings if s.key == key)
        found = self.env.get(setting.env)
        if found:
            return found
        if not setting.secret and self.config.get(key) not in (None, ""):
            return str(self.config[key])
        return None

    def missing(self) -> list[str]:
        """Human-readable reasons this store cannot run yet; empty when it is ready."""
        return [
            f"{s.prompt} ({s.env})" for s in self.settings if s.required and not self.value(s.key)
        ]

    def fetch_library(self) -> list[Game]:
        raise NotImplementedError

    def enrich(self, games: list[Game], cache: dict, progress: Callable[[str], None]) -> None:
        """Optional: fill genres/scores/cover art. `cache` is a persistent dict owned by the store;
        mutate it and it is saved after the call."""

    def store_url(self, game: Game) -> str | None:
        return None
