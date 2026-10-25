"""Price and bundle lookups on IsThereAnyDeal (https://isthereanydeal.com/apps/my/ for an API key)."""

from __future__ import annotations

import requests

from whattoplay.models import normalize_name as normalize

API_BASE = "https://api.isthereanydeal.com"


class DealsError(RuntimeError):
    pass


def _request(method: str, path: str, **kwargs):
    try:
        response = requests.request(method, f"{API_BASE}{path}", timeout=15, **kwargs)
        response.raise_for_status()
        return response.json()
    except (requests.RequestException, ValueError) as exc:
        raise DealsError(f"IsThereAnyDeal request failed: {exc}") from exc


def lookup(api_key: str, title: str | None = None, appid: int | None = None) -> dict | None:
    params: dict = {"key": api_key}
    if appid is not None:
        params["appid"] = appid
    if title is not None:
        params["title"] = title
    data = _request("GET", "/games/lookup/v1", params=params)
    return data["game"] if data.get("found") else None


def price(
    api_key: str,
    title: str | None,
    appid: int | None,
    country: str,
    shop: str | None = None,
    on_sale: bool = False,
) -> dict | None:
    """Current prices per shop (`cut` is 0 when not discounted) and the all-time low.

    `on_sale` asks IsThereAnyDeal for discounted offers only; for a game with no sale right now
    its answer is empty, which is why it is opt-in."""
    game = lookup(api_key, title=title, appid=appid)
    if game is None:
        return None
    params = {"key": api_key, "country": country}
    if on_sale:
        params["deals"] = "true"
    data = _request("POST", "/games/prices/v3", params=params, json=[game["id"]])
    entry = data[0] if data else {}
    deals = entry.get("deals", [])
    if shop:
        deals = [d for d in deals if shop.lower() in d["shop"]["name"].lower()]
    return {
        "title": game["title"],
        "id": game["id"],
        "historyLow": entry.get("historyLow"),
        "deals": deals,
    }


def bundles(api_key: str, owned_titles: set[str], country: str, limit: int) -> list[dict]:
    """Active bundles; each game is flagged with whether it is already in the library."""
    data = _request(
        "GET",
        "/bundles/v1",
        params={
            "key": api_key,
            "country": country,
            "limit": limit,
            "mature": "false",
            "expired": "false",
        },
    )
    result = []
    for b in data:
        games = [g["title"] for tier in b.get("tiers", []) for g in tier.get("games", [])]
        result.append(
            {
                "title": b["title"],
                "store": b.get("page", {}).get("name"),
                "url": b.get("url"),
                "expiry": b.get("expiry"),
                "games": games,
                "not_owned": [g for g in games if normalize(g) not in owned_titles],
            }
        )
    return result
