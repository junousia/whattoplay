---
name: whattoplay
description: Help the user pick something to play from games they already own (Steam, Epic, plugin stores such as PSN), keep a playing/queued/finished list, and check prices and bundles. Use when the user asks what to play, wants a backlog suggestion, says they started, finished or don't want a game, or asks about game deals.
---

# whattoplay

A CLI that keeps a cached library from one or more store backends and filters it. The CLI only filters and sorts; **you** make the actual recommendation. Run it as `uvx whattoplay <command>` (or `whattoplay` when installed). Always pass `--json` and turn the result into a normal conversational reply; never paste raw JSON into the chat.

Data lives in `$WHATTOPLAY_DIR` (default `~/.local/share/whattoplay`): library cache, play status and the user's own settings. Check the directory for a `preferences.md`: if it exists, read it before recommending anything. It holds the user's taste and rules (genres or art styles to avoid, which store purchases must be on, how high the bar is for buying, how to format game mentions).

## First-time setup

1. `whattoplay stores --json`: shows each backend, whether it is enabled and what it still needs.
2. Credentials are environment variables listed there (or lines in `<dir>/.env`, mode 600). Secrets are never read from `config.toml`. `whattoplay configure <store>` does this interactively; ask the user to run it themselves (`! whattoplay configure steam`) so secrets don't pass through the chat.
3. `whattoplay refresh --json`: fetches every ready store. A failing store is reported and keeps its previously cached games; the others still refresh.

## Commands

| Command | Use |
|---|---|
| `suggest --limit 20 [--genre X] [--exclude-genre X] [--min-score N] [--platform P] [--threshold-minutes N] [--shuffle [--seed N]]` | Barely-played games (default ≤120 min, unknown playtime included), least played first, balanced across platforms; `--shuffle` randomizes. A game owned on several stores counts once. Skips anything with a status. Not quality-ranked |
| `library [--status S \| --unmarked] [--platform P]` | Whole cached library, for questions the suggest pool is too narrow for |
| `find <name…>` | Look a game up by name |
| `mark <platform>:<id> playing\|queued\|finished\|dismissed\|clear [--note T]` | Track status; `--name "Game"` instead of the id works when the name is unambiguous |
| `queue` | What the user is playing now or has queued |
| `stats` | Unique games, counts by status and platform, and when the library was last refreshed (`age_days`) |
| `refresh [--store S]` | Re-fetch libraries. Slow for Steam (rate-limited metadata) and it hits external services: only when asked, or when `suggest` reports `empty` |
| `stores`, `configure <store> [--enable\|--disable]` | Backends and their setup |
| `deals price --title T [--appid N] [--country FI] [--shop steam]` | Current prices and all-time low (IsThereAnyDeal, needs `ITAD_API_KEY`) |
| `deals bundles [--limit N] [--country FI]` | Active bundles, with the games the user does not own already |

The same game owned on several stores (or PS4/PS5 editions) is one game: a `mark` applies to every copy, `also_on` lists the other copies' keys, and missing genres or scores are filled in from the copy that has them. If `stats` shows `age_days` of a few weeks, offer a `refresh`.

Game records carry `name`, `platform`, `external_id`, `key` (`platform:id`), `playtime_minutes`, `genres`, `metacritic_score`, `store_url` (for Epic a store search link, not the game's own page), `header_image_url`, `status`, `note`, `also_on`. Playtime `null` means the store exposes none (for example Epic), not "never played". Empty `genres` is a data gap, not a fact about the game.

## Picking well

`suggest` is deterministic: reading off the first results gives the user the same games every time. Instead:

1. Pull a wider pool than you will show (`--limit 20`, or `library` filtered yourself).
2. Narrow by what was asked: mood, genre, time budget, platform, review quality; then by the user's `preferences.md`.
3. Prefer variety over the least-played game each time, and do not repeat a game already suggested in the conversation.
4. Offer 2-4 picks with a one-line reason grounded in the data (genre, score, how long it has sat untouched). Do not invent plot details you have no data on.
5. Always include `store_url` when there is one. Never guess store links or appids for games outside the library: look them up.
6. If nothing fits, say so and offer the closest alternative.

Keep the status current: when the user starts a game `mark … playing`; finishes it `mark … finished`; rejects a specific suggestion `mark … dismissed` and offer a replacement from the pool you already have; agrees to play something later `mark … queued`.

## Deals

Only recommend a purchase when it is a genuine must-play for this user, not just thematically fitting filler: their backlog is usually already huge, so pointing back at owned games is often the better answer. Check redemption platform and shop before recommending a bundle, and apply the user's store rules from `preferences.md`.

## Errors

If a command returns `{"status": "error", ...}` or exits non-zero, explain briefly what went wrong in plain words; never show a traceback. `{"status": "empty"}` from `suggest` or `library` means no cached library: run `refresh`.

## Adding a store

Backends are plugins: drop a Python file with a `Store` subclass into `<dir>/plugins/`, or install a package that registers the `whattoplay.stores` entry point. See `examples/example_store.py` and the README.
