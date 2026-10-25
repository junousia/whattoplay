from __future__ import annotations

import time
from collections.abc import Callable

import requests

from whattoplay.models import Game
from whattoplay.stores.base import Setting, Store, StoreError

OWNED_GAMES_URL = "https://api.steampowered.com/IPlayerService/GetOwnedGames/v0001/"
APPDETAILS_URL = "https://store.steampowered.com/api/appdetails"
RESOLVE_VANITY_URL = "https://api.steampowered.com/ISteamUser/ResolveVanityURL/v0001/"
METADATA_DELAY_SECONDS = 1.5  # the store API is rate limited


def resolve_steam_id(api_key: str, identifier: str) -> str:
    """Accepts a SteamID64, a profile URL or a custom URL name."""
    identifier = identifier.strip().rstrip("/")
    if "/" in identifier:
        identifier = identifier.rsplit("/", 1)[-1]
    if identifier.isdigit() and len(identifier) == 17:
        return identifier
    try:
        response = requests.get(
            RESOLVE_VANITY_URL,
            params={"key": api_key, "vanityurl": identifier, "format": "json"},
            timeout=10,
        )
        response.raise_for_status()
        result = response.json().get("response", {})
    except (requests.RequestException, ValueError) as exc:
        raise StoreError(f"Steam API request failed: {exc}") from exc
    if result.get("success") != 1 or "steamid" not in result:
        raise StoreError(
            f"Could not resolve Steam profile '{identifier}'. "
            "Check the profile name, or use your 17-digit SteamID64 directly."
        )
    return result["steamid"]


class SteamStore(Store):
    name = "steam"
    label = "Steam"
    settings = (
        Setting(
            "api_key",
            "STEAM_API_KEY",
            "Steam Web API key (https://steamcommunity.com/dev/apikey)",
            secret=True,
        ),
        Setting("steam_id64", "STEAM_ID64", "SteamID64 or custom profile URL name"),
    )

    def fetch_library(self) -> list[Game]:
        try:
            response = requests.get(
                OWNED_GAMES_URL,
                params={
                    "key": self.value("api_key"),
                    "steamid": self.value("steam_id64"),
                    "format": "json",
                    "include_appinfo": "true",
                    "include_played_free_games": "true",
                },
                timeout=10,
            )
            response.raise_for_status()
            games = response.json().get("response", {}).get("games")
        except (requests.RequestException, ValueError) as exc:
            raise StoreError(f"Steam API request failed: {exc}") from exc
        if games is None:
            raise StoreError(
                "Steam API returned no games data (profile may be private, or the SteamID64 is invalid)"
            )
        return [
            Game(
                name=g["name"],
                platform=self.name,
                external_id=str(g["appid"]),
                playtime_minutes=g.get("playtime_forever", 0),
                store_url=f"https://store.steampowered.com/app/{g['appid']}/",
            )
            for g in games
        ]

    def enrich(self, games: list[Game], cache: dict, progress: Callable[[str], None]) -> None:
        todo = [g for g in games if g.external_id not in cache]
        for i, game in enumerate(todo, 1):
            fetched = fetch_app_metadata(game.external_id)
            if fetched is not None:  # None = unknown yet; do not cache it as "no data"
                cache[game.external_id] = fetched
            progress(f"Steam metadata {i}/{len(todo)}")
            time.sleep(METADATA_DELAY_SECONDS)
        for game in games:
            meta = cache.get(game.external_id)
            if meta:
                game.genres = meta.get("genres", [])
                game.metacritic_score = meta.get("metacritic_score")
                game.metacritic_url = meta.get("metacritic_url")
                game.header_image_url = meta.get("header_image_url")


def fetch_app_metadata(appid: str) -> dict | None:
    try:
        response = requests.get(APPDETAILS_URL, params={"appids": appid}, timeout=10)
        response.raise_for_status()
        entry = response.json().get(str(appid), {})
    except (requests.RequestException, ValueError):
        return None
    if not entry.get("success"):
        return None
    data = entry.get("data", {})
    metacritic = data.get("metacritic") or {}
    return {
        "genres": [g["description"] for g in data.get("genres", []) if "description" in g],
        "metacritic_score": metacritic.get("score"),
        "metacritic_url": metacritic.get("url"),
        "header_image_url": data.get("header_image"),
    }
