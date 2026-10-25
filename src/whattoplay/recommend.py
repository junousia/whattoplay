from __future__ import annotations

from whattoplay.models import Game


def _rank(game: Game) -> tuple[bool, int, str]:
    return (game.playtime_minutes is None, game.playtime_minutes or 0, game.name)


def suggest(
    games: list[Game],
    threshold_minutes: int = 120,
    limit: int = 10,
    exclude: set[str] = frozenset(),
    genres: list[str] | None = None,
    platform: str | None = None,
) -> list[Game]:
    """Candidate pool of barely-played games, least played first, balanced across platforms.

    Deterministic and not quality-ranked: the caller (human or agent) does the actual picking.
    """
    wanted = {g.lower() for g in genres} if genres else set()
    candidates = sorted(
        (
            g
            for g in games
            if (g.playtime_minutes is None or g.playtime_minutes <= threshold_minutes)
            and g.key not in exclude
            and (not wanted or wanted & {x.lower() for x in g.genres})
            and (platform is None or g.platform == platform)
        ),
        key=_rank,
    )
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
    return sorted(picked, key=_rank)[:limit]


def find(games: list[Game], query: str) -> list[Game]:
    """Exact (case-insensitive) name match wins; otherwise all substring matches."""
    q = query.strip().lower()
    exact = [g for g in games if g.name.lower() == q]
    return exact or [g for g in games if q in g.name.lower()]
