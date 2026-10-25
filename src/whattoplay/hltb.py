"""Time-to-beat data from HowLongToBeat.

HowLongToBeat has no official API: this uses the unofficial `howlongtobeatpy` scraper
(`pip install 'whattoplay[hltb]'`), so it can break when the site changes. Lookups are slow on
purpose, one at a time, and cached on disk (misses included) so each game is asked at most once.
"""

from __future__ import annotations

import time

from whattoplay import storage
from whattoplay.models import Game, normalize_name

CACHE_NAME = "hltb"
LOOKUP_DELAY_SECONDS = 1.0
MAX_CONSECUTIVE_FAILURES = 3  # then stop: the site is rate-limiting or blocking us
MIN_SIMILARITY = 0.85  # when no result matches the title exactly


class HltbUnavailable(RuntimeError):
    pass


def _hours(*values) -> float | None:
    for v in values:
        if v and v > 0:
            return round(float(v), 1)
    return None


def pick(results: list, name: str):
    """The result for `name`: an exact (normalized) title match, else the best sufficiently similar one."""
    wanted = normalize_name(name)
    exact = [r for r in results if normalize_name(r.game_name) == wanted]
    if exact:
        return max(exact, key=lambda r: r.similarity)
    close = [r for r in results if r.similarity >= MIN_SIMILARITY]
    return max(close, key=lambda r: r.similarity) if close else None


def search(name: str):
    """Raw HowLongToBeat results, or raises HltbUnavailable when the package is missing."""
    try:
        from howlongtobeatpy import HowLongToBeat
    except ImportError as exc:
        raise HltbUnavailable(
            "howlongtobeatpy is not installed (pip install 'whattoplay[hltb]')"
        ) from exc
    return HowLongToBeat().search(name) or []


def lookup(name: str) -> dict | None:
    """`{}` when HowLongToBeat has no match (cacheable), None when the lookup itself failed."""
    try:
        results = search(name)
    except HltbUnavailable:
        raise
    except Exception:  # noqa: BLE001 - scraper errors are many and varied; treat as "try later"
        return None
    best = pick(results, name)
    if best is None:
        return {}
    return {
        "main_hours": _hours(best.main_story, best.main_extra),
        "extra_hours": _hours(best.main_extra),
        "completionist_hours": _hours(best.completionist),
        "hltb_url": f"https://howlongtobeat.com/game/{best.game_id}",
    }


def load_times(data_dir) -> dict:
    return storage.load_cache(data_dir, CACHE_NAME)


def apply_times(games: list[Game], times: dict) -> None:
    """Fills the time fields from the cache; a game's times apply to all its copies."""
    for g in games:
        entry = times.get(g.group)
        if entry:
            g.main_hours = entry.get("main_hours")
            g.extra_hours = entry.get("extra_hours")
            g.completionist_hours = entry.get("completionist_hours")
            g.hltb_url = entry.get("hltb_url")


class TimeFetcher:
    """Looks up uncached games one by one, up to `budget` lookups, saving the cache as it goes."""

    def __init__(self, data_dir, budget: int, progress=lambda _msg: None):
        self.data_dir = data_dir
        self.times = load_times(data_dir)
        self.budget = budget
        self.progress = progress
        self.fetched = 0
        self.failures = 0

    @property
    def blocked(self) -> bool:
        """HowLongToBeat keeps failing; further lookups would only hammer it."""
        return self.failures >= MAX_CONSECUTIVE_FAILURES

    def known(self, game: Game) -> bool:
        return game.group in self.times

    def ensure(self, game: Game) -> bool:
        """True when the game's time is now known (possibly as "no match")."""
        if self.known(game):
            return True
        if self.budget <= 0 or self.blocked:
            return False
        self.budget -= 1
        result = lookup(game.name)
        time.sleep(LOOKUP_DELAY_SECONDS)
        if result is None:
            self.failures += 1
            return False
        self.failures = 0
        self.times[game.group] = result
        self.fetched += 1
        storage.save_cache(self.data_dir, CACHE_NAME, self.times)
        self.progress(f"HowLongToBeat {game.name}: {result.get('main_hours') or 'no match'}")
        return True
