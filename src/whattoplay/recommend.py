from __future__ import annotations

import random
from collections.abc import Callable

from whattoplay.models import Game


def _rank(game: Game) -> tuple[bool, int, str]:
    return (game.playtime_minutes is None, game.playtime_minutes or 0, game.name)


def group_playtime(games: list[Game]) -> dict[str, int | None]:
    """Most known playtime per game, across every store that has it."""
    best: dict[str, int | None] = {}
    for g in games:
        known = best.get(g.group)
        if g.playtime_minutes is not None and (known is None or g.playtime_minutes > known):
            best[g.group] = g.playtime_minutes
        else:
            best.setdefault(g.group, known)
    return best


def suggest(
    games: list[Game],
    threshold_minutes: int = 120,
    limit: int = 10,
    exclude: set[str] = frozenset(),
    genres: list[str] | None = None,
    platform: str | None = None,
    exclude_genres: list[str] | None = None,
    min_score: int | None = None,
    shuffle: random.Random | None = None,
    keep: Callable[[Game], bool] | None = None,
) -> list[Game]:
    """Candidate pool of barely-played games, least played first, balanced across platforms.

    A game owned on several stores counts once, using the largest playtime known for it.
    Deterministic unless `shuffle` is given, and not quality-ranked: the caller (human or agent)
    does the actual picking.
    """
    wanted = {g.lower() for g in genres} if genres else set()
    unwanted = {g.lower() for g in exclude_genres} if exclude_genres else set()
    played = group_playtime(games)
    candidates: list[Game] = []
    seen: set[str] = set()
    for g in sorted(games, key=_rank):
        have = {x.lower() for x in g.genres}
        if (
            g.group in seen
            or g.key in exclude
            or (played[g.group] is not None and played[g.group] > threshold_minutes)
            or (wanted and not wanted & have)
            or (unwanted and unwanted & have)
            or (min_score is not None and (g.metacritic_score or 0) < min_score)
            or (platform is not None and g.platform != platform)
        ):
            continue
        if keep is not None and not keep(g):  # last, so expensive checks only see real candidates
            continue
        seen.add(g.group)
        candidates.append(g)
    if shuffle is not None:
        shuffle.shuffle(candidates)
    platforms = sorted({g.platform for g in candidates})
    if platform is not None or len(platforms) <= 1 or limit <= 0:
        return candidates[:limit]

    quota = max(1, limit // len(platforms))
    picked = [g for p in platforms for g in [c for c in candidates if c.platform == p][:quota]]
    taken = {g.key for g in picked}
    for g in candidates:
        if len(picked) >= limit:
            break
        if g.key not in taken:
            picked.append(g)
            taken.add(g.key)
    return (picked if shuffle is not None else sorted(picked, key=_rank))[:limit]


def find(games: list[Game], query: str) -> list[Game]:
    """Exact (case-insensitive) name match wins; otherwise all substring matches."""
    q = query.strip().lower()
    exact = [g for g in games if g.name.lower() == q]
    return exact or [g for g in games if q in g.name.lower()]
