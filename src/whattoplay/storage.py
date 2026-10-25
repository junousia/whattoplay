"""Everything persisted under the data directory (library cache, store caches, play status)."""

from __future__ import annotations

import json
import os
from datetime import UTC, datetime
from pathlib import Path

from whattoplay.models import Game

STATUSES = ("playing", "queued", "finished", "dismissed")


def _write_json(path: Path, payload: object) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_name(f"{path.name}.{os.getpid()}.tmp")
    tmp.write_text(json.dumps(payload, indent=2))
    tmp.replace(path)  # atomic: a crash never leaves a truncated file


def load_library(data_dir: Path) -> list[Game]:
    path = data_dir / "library.json"
    if not path.exists():
        return []
    return [Game.from_dict(item) for item in json.loads(path.read_text())]


def save_library(data_dir: Path, games: list[Game]) -> None:
    _write_json(data_dir / "library.json", [g.to_dict() for g in games])


def load_cache(data_dir: Path, store: str) -> dict:
    path = data_dir / "cache" / f"{store}.json"
    return json.loads(path.read_text()) if path.exists() else {}


def save_cache(data_dir: Path, store: str, cache: dict) -> None:
    _write_json(data_dir / "cache" / f"{store}.json", cache)


def load_state(data_dir: Path) -> dict[str, dict]:
    """`{"platform:id": {"status": ..., "note": ..., "updated": ...}}`. Reads the legacy
    `dismissed.json` of earlier versions when no `state.json` exists yet."""
    path = data_dir / "state.json"
    if path.exists():
        return json.loads(path.read_text()).get("games", {})
    legacy = data_dir / "dismissed.json"
    if legacy.exists():
        return {
            f"{item['platform']}:{item['external_id']}": {
                "status": "dismissed",
                "note": None,
                "updated": None,
            }
            for item in json.loads(legacy.read_text())
        }
    return {}


def set_status(data_dir: Path, key: str, status: str | None, note: str | None = None) -> None:
    """`status=None` clears the entry."""
    if status is not None and status not in STATUSES:
        raise ValueError(f"status must be one of {', '.join(STATUSES)} (or clear)")
    state = load_state(data_dir)
    if status is None:
        state.pop(key, None)
    else:
        state[key] = {
            "status": status,
            "note": note,
            "updated": datetime.now(UTC).isoformat(timespec="seconds"),
        }
    _write_json(data_dir / "state.json", {"version": 1, "games": state})


def merge_libraries(*lists: list[Game]) -> list[Game]:
    """One entry per (platform, id); on duplicates keep the one with more playtime data."""
    merged: dict[str, Game] = {}
    for games in lists:
        for game in games:
            existing = merged.get(game.key)
            rank = -1 if game.playtime_minutes is None else game.playtime_minutes
            if existing is None or rank > (
                -1 if existing.playtime_minutes is None else existing.playtime_minutes
            ):
                merged[game.key] = game
    return list(merged.values())
