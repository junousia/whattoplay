from __future__ import annotations

import time
from collections.abc import Callable
from urllib.parse import quote

import requests

from whattoplay.models import Game, normalize_name
from whattoplay.stores.base import Store, StoreError
from whattoplay.stores.steam import METADATA_DELAY_SECONDS, fetch_app_metadata

STEAM_SEARCH_URL = "https://store.steampowered.com/api/storesearch/"


class EpicStore(Store):
    """Epic Games Store via `legendary` (`pip install whattoplay[epic]`, then `legendary auth`)."""

    name = "epic"
    label = "Epic Games Store"

    def _core(self):
        try:
            from legendary.core import LegendaryCore
        except ImportError as exc:
            raise StoreError("legendary is not installed (pip install 'whattoplay[epic]')") from exc
        return LegendaryCore()

    def missing(self) -> list[str]:
        try:
            import legendary.core  # noqa: F401
        except ImportError:
            return ["legendary is not installed (pip install 'whattoplay[epic]')"]
        return []

    def store_url(self, game: Game) -> str | None:
        # Epic page slugs are not in the library data, so link to the store's search for the title.
        return f"https://store.epicgames.com/browse?q={quote(game.name)}"

    def fetch_library(self) -> list[Game]:
        core = self._core()
        try:
            logged_in = core.login()
        except ValueError as exc:
            raise StoreError(
                "legendary has no saved Epic login; run `legendary auth` first"
            ) from exc
        if not logged_in:
            raise StoreError(
                "legendary's saved Epic login is no longer valid; run `legendary auth` again"
            )
        return [
            Game(
                name=g.app_title, platform=self.name, external_id=g.app_name, playtime_minutes=None
            )
            for g in core.get_game_list(update_assets=True)
        ]

    def enrich(self, games: list[Game], cache: dict, progress: Callable[[str], None]) -> None:
        """Epic has no genre or score data, so look each title up in the Steam store by exact name.
        Epic exclusives stay without metadata; lookups are cached (misses too, as `{}`)."""
        todo = [g for g in games if g.external_id not in cache]
        for i, game in enumerate(todo, 1):
            result = steam_metadata_by_name(game.name)
            if result is not None:  # None = lookup failed, retry next time
                cache[game.external_id] = result
            progress(f"Epic metadata via Steam {i}/{len(todo)}")
            time.sleep(METADATA_DELAY_SECONDS)
        for game in games:
            meta = cache.get(game.external_id)
            if meta:
                game.genres = meta.get("genres", [])
                game.metacritic_score = meta.get("metacritic_score")
                game.metacritic_url = meta.get("metacritic_url")
                game.header_image_url = meta.get("header_image_url")


def steam_metadata_by_name(name: str) -> dict | None:
    """Metadata of the Steam app whose name matches exactly, `{}` if there is none, None on error."""
    try:
        response = requests.get(
            STEAM_SEARCH_URL, params={"term": name, "cc": "us", "l": "en"}, timeout=10
        )
        response.raise_for_status()
        items = response.json().get("items", [])
    except (requests.RequestException, ValueError):
        return None
    wanted = normalize_name(name)
    match = next(
        (
            i
            for i in items
            if i.get("type") == "app" and normalize_name(i.get("name", "")) == wanted
        ),
        None,
    )
    if match is None:
        return {}
    return fetch_app_metadata(str(match["id"]))
