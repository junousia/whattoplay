from __future__ import annotations

import argparse
import getpass
import json
import random
import sys
from datetime import UTC, datetime
from pathlib import Path

from whattoplay import __version__, deals, hltb, recommend, storage
from whattoplay.config import load_config, load_env, resolve_data_dir, save_config, update_env_file
from whattoplay.models import Game
from whattoplay.stores import build_stores
from whattoplay.stores.base import Store, StoreError

HELP_EPILOG = """\
Games are addressed as <platform>:<id> (e.g. steam:620, shown by suggest/library/find) or with --name.
Data lives in --dir, $WHATTOPLAY_DIR or ~/.local/share/whattoplay.
"""


class CliError(Exception):
    def __init__(self, message: str, **extra):
        super().__init__(message)
        self.extra = extra


def emit(args, payload, text: str | None = None) -> None:
    if args.json:
        print(json.dumps(payload))
    else:
        print(text if text is not None else json.dumps(payload, indent=2))


def game_line(game: Game, state: dict) -> str:
    playtime = "unknown" if game.playtime_minutes is None else f"{game.playtime_minutes} min"
    status = state.get(game.key, {}).get("status")
    extras = [f"genres: {', '.join(game.genres)}"] if game.genres else []
    if game.metacritic_score is not None:
        extras.append(f"metacritic: {game.metacritic_score}")
    if game.main_hours is not None:
        extras.append(f"~{game.main_hours:g} h to beat")
    if status:
        extras.append(status)
    suffix = f" - {'; '.join(extras)}" if extras else ""
    return f"{game.name} [{game.key}] ({playtime} played){suffix}"


def effective_state(games: list[Game], state: dict) -> dict:
    """Status of a game applies to every copy of it (same name, any store)."""
    by_group: dict[str, dict] = {}
    for g in games:
        if g.key in state:
            by_group.setdefault(g.group, state[g.key])
    return {
        g.key: state.get(g.key) or by_group[g.group]
        for g in games
        if g.key in state or g.group in by_group
    }


def with_status(games: list[Game], state: dict, library: list[Game]) -> list[dict]:
    state = effective_state(library, state)
    copies: dict[str, list[str]] = {}
    for g in library:
        copies.setdefault(g.group, []).append(g.key)
    return [
        {
            **g.to_dict(),
            "status": state.get(g.key, {}).get("status"),
            "note": state.get(g.key, {}).get("note"),
            "also_on": [k for k in copies[g.group] if k != g.key],
        }
        for g in games
    ]


class Context:
    def __init__(self, args):
        self.dir: Path = resolve_data_dir(args.dir)
        self.env = load_env(self.dir)
        self.config = load_config(self.dir)
        self.stores, self.plugin_errors = build_stores(self.dir, self.config, self.env)

    def enabled(self, name: str) -> bool:
        return self.config.get("stores", {}).get(name, {}).get("enabled", True) is not False

    def library(self) -> list[Game]:
        games = storage.load_library(self.dir)
        hltb.apply_times(games, hltb.load_times(self.dir))
        storage.share_metadata(games)  # also fixes libraries cached before this existed
        for g in games:  # caches written before store_url was stored
            if g.store_url is None and g.platform in self.stores:
                g.store_url = self.stores[g.platform].store_url(g)
        return games


def resolve_game(ctx: Context, key: str | None, name: str | None) -> Game:
    games = ctx.library()
    if key:
        found = next((g for g in games if g.key == key), None)
        if found is None:
            raise CliError(f"no game {key} in the library (run `whattoplay refresh`?)")
        return found
    if not name:
        raise CliError("give a <platform>:<id> or --name")
    matches = recommend.find(games, name)
    if not matches:
        raise CliError(f'no game matches "{name}"')
    if len({g.group for g in matches}) > 1:
        raise CliError(
            f'"{name}" is ambiguous, use <platform>:<id>',
            candidates=[{"name": g.name, "key": g.key} for g in matches[:10]],
        )
    return matches[0]


def cmd_stores(ctx: Context, args) -> None:
    rows = []
    for name, store in sorted(ctx.stores.items()):
        missing = store.missing()
        rows.append(
            {
                "name": name,
                "label": store.label or name,
                "enabled": ctx.enabled(name),
                "ready": not missing,
                "missing": missing,
                "settings": [
                    {"key": s.key, "env": s.env, "secret": s.secret} for s in store.settings
                ],
            }
        )
    text = "\n".join(
        f"{r['name']:<10} {'enabled' if r['enabled'] else 'disabled':<9} "
        + ("ready" if r["ready"] else "needs: " + "; ".join(r["missing"]))
        for r in rows
    )
    if ctx.plugin_errors:
        text += "\n" + "\n".join(f"warning: {e}" for e in ctx.plugin_errors)
    emit(args, {"status": "ok", "stores": rows, "plugin_errors": ctx.plugin_errors}, text)


def cmd_configure(ctx: Context, args) -> None:
    store = ctx.stores.get(args.store)
    if store is None:
        raise CliError(f"unknown store {args.store!r}; see `whattoplay stores`")
    if args.disable or args.enable:
        ctx.config.setdefault("stores", {}).setdefault(args.store, {})["enabled"] = bool(
            args.enable
        )
        save_config(ctx.dir, ctx.config)
        emit(
            args,
            {"status": "ok", "store": args.store, "enabled": bool(args.enable)},
            f"{args.store}: {'enabled' if args.enable else 'disabled'}",
        )
        return
    if not sys.stdin.isatty():
        raise CliError(
            "configure is interactive. Non-interactively, set the environment variables listed by "
            "`whattoplay stores --json` (or put them in <dir>/.env) and add non-secret values to config.toml."
        )
    table = dict(ctx.config.get("stores", {}).get(args.store, {}))
    secrets: dict[str, str] = {}
    for setting in store.settings:
        reply = (getpass.getpass if setting.secret else input)(f"{setting.prompt}: ").strip()
        if not reply:
            continue
        if setting.secret:
            secrets[setting.env] = reply
        else:
            table[setting.key] = reply
    if args.store == "steam" and table.get("steam_id64"):
        from whattoplay.stores.steam import resolve_steam_id

        key = secrets.get("STEAM_API_KEY") or ctx.env.get("STEAM_API_KEY", "")
        table["steam_id64"] = resolve_steam_id(key, table["steam_id64"])
    table.setdefault("enabled", True)
    ctx.config.setdefault("stores", {})[args.store] = table
    save_config(ctx.dir, ctx.config)
    if secrets:
        update_env_file(ctx.dir, secrets)
    print(f"Saved {args.store} settings to {ctx.dir}.")


def refresh_store(ctx: Context, store: Store, quiet: bool) -> list[Game]:
    games = store.fetch_library()
    cache = storage.load_cache(ctx.dir, store.name)
    try:
        store.enrich(
            games, cache, (lambda _msg: None) if quiet else lambda msg: print(msg, file=sys.stderr)
        )
    finally:
        storage.save_cache(ctx.dir, store.name, cache)  # keep partial progress between runs
    for g in games:
        if g.store_url is None:
            g.store_url = store.store_url(g)
    return games


def cmd_refresh(ctx: Context, args) -> None:
    if args.store and args.store not in ctx.stores:
        raise CliError(f"unknown store {args.store!r}; see `whattoplay stores`")
    names = [args.store] if args.store else [n for n in sorted(ctx.stores) if ctx.enabled(n)]
    per_store: dict[str, dict] = {}
    fetched: dict[str, list[Game]] = {}
    for name in names:
        store = ctx.stores[name]
        missing = store.missing()
        if missing:
            per_store[name] = {
                "status": "skipped",
                "reason": "not configured: " + "; ".join(missing),
            }
            continue
        try:
            fetched[name] = refresh_store(ctx, store, quiet=args.json)
            per_store[name] = {"status": "ok", "count": len(fetched[name])}
        except StoreError as exc:
            per_store[name] = {"status": "error", "message": str(exc)}
    if not fetched:
        raise CliError("no store could be refreshed", stores=per_store)
    # Stores that were not refreshed keep their cached games: failed or skipped ones, and (with
    # --store) every other store. Only stores that are now disabled are dropped.
    keep_platforms = {n for n in ctx.stores if n not in fetched and (args.store or ctx.enabled(n))}
    keep_platforms |= {
        g.platform for g in storage.load_library(ctx.dir) if g.platform not in ctx.stores
    }
    kept = [g for g in storage.load_library(ctx.dir) if g.platform in keep_platforms]
    merged = storage.merge_libraries(kept, *fetched.values())
    storage.share_metadata(merged)
    storage.save_library(ctx.dir, merged)
    meta = storage.load_meta(ctx.dir)
    meta["refreshed_at"] = datetime.now(UTC).isoformat(timespec="seconds")
    storage.save_meta(ctx.dir, meta)
    text = f"Refreshed library: {len(merged)} games.\n" + "\n".join(
        f"  {n}: {r['status']}"
        + (f" ({r['count']})" if "count" in r else f" - {r.get('reason') or r.get('message')}")
        for n, r in per_store.items()
    )
    emit(args, {"status": "ok", "total": len(merged), "stores": per_store}, text)


def hours_filter(ctx: Context, args):
    """`--max-hours` / `--min-hours` predicate. Looks up at most `--lookup` games that are not
    cached yet (HowLongToBeat is slow); games with no known time are dropped unless
    `--include-unknown-time`."""
    if args.max_hours is None and args.min_hours is None:
        return None
    fetcher = hltb.TimeFetcher(
        ctx.dir,
        args.lookup,
        (lambda _m: None) if args.json else lambda m: print(m, file=sys.stderr),
    )

    def keep(game: Game) -> bool:
        try:
            known = fetcher.ensure(game)
        except hltb.HltbUnavailable as exc:
            raise CliError(str(exc)) from exc
        entry = fetcher.times.get(game.group) if known else None
        hours = (entry or {}).get("main_hours")
        if hours is None:
            return args.include_unknown_time
        game.main_hours = hours
        game.extra_hours = entry.get("extra_hours")
        game.completionist_hours = entry.get("completionist_hours")
        game.hltb_url = entry.get("hltb_url")
        return (args.max_hours is None or hours <= args.max_hours) and (
            args.min_hours is None or hours >= args.min_hours
        )

    ctx.hltb_fetcher = fetcher
    return keep


def cmd_times(ctx: Context, args) -> None:
    games = ctx.library()
    state = effective_state(games, storage.load_state(ctx.dir))
    if args.query:
        pool = recommend.find(games, " ".join(args.query))[:1]
        if not pool:
            raise CliError(f'no game matches "{" ".join(args.query)}"')
    else:  # the games suggest would pick from, in its order
        pool = recommend.suggest(games, args.threshold_minutes, len(games), set(state))
    fetcher = hltb.TimeFetcher(
        ctx.dir, args.limit, lambda m: None if args.json else print(m, file=sys.stderr)
    )
    try:
        if args.query and args.refresh:
            fetcher.times.pop(pool[0].group, None)
        for g in pool:
            fetcher.ensure(g)
    except hltb.HltbUnavailable as exc:
        raise CliError(str(exc)) from exc
    hltb.apply_times(pool, fetcher.times)
    remaining = sum(1 for g in pool if not fetcher.known(g))
    result = {"status": "ok", "fetched": fetcher.fetched, "remaining": remaining}
    if fetcher.blocked:
        result["status"] = "blocked"
        result["message"] = (
            "HowLongToBeat is rate-limiting or blocking lookups; wait a few hours and retry"
        )
    if args.query:
        result["game"] = with_status(pool, state, games)[0]
    emit(
        args,
        result,
        ("HowLongToBeat is rate-limiting us, stopped early. " if fetcher.blocked else "")
        + f"fetched {fetcher.fetched}, {remaining} candidates still without a time"
        + (f"\n{game_line(pool[0], state)}" if args.query else ""),
    )


def cmd_suggest(ctx: Context, args) -> None:
    games = ctx.library()
    if not games:
        emit(
            args,
            {"status": "empty", "message": "No cached library. Run `whattoplay refresh` first."},
        )
        return
    state = effective_state(games, storage.load_state(ctx.dir))
    picks = recommend.suggest(
        games,
        args.threshold_minutes,
        args.limit,
        set(state),
        args.genre,
        args.platform,
        exclude_genres=args.exclude_genre,
        min_score=args.min_score,
        shuffle=(random.Random(args.seed) if args.shuffle or args.seed is not None else None),
        keep=hours_filter(ctx, args),
    )
    fetcher = getattr(ctx, "hltb_fetcher", None)
    if fetcher is not None and fetcher.blocked:
        print(
            "warning: HowLongToBeat is rate-limiting lookups; results may be incomplete",
            file=sys.stderr,
        )
    if not picks:
        emit(args, {"status": "empty", "message": "No unplayed/low-playtime games match."})
        return
    emit(args, with_status(picks, state, games), "\n".join(game_line(g, state) for g in picks))


def cmd_library(ctx: Context, args) -> None:
    games = ctx.library()
    if not games:
        emit(
            args,
            {"status": "empty", "message": "No cached library. Run `whattoplay refresh` first."},
        )
        return
    state = effective_state(games, storage.load_state(ctx.dir))
    shown = games
    if args.status:
        shown = [g for g in shown if state.get(g.key, {}).get("status") == args.status]
    elif args.unmarked:
        shown = [g for g in shown if g.key not in state]
    if args.platform:
        shown = [g for g in shown if g.platform == args.platform]
    shown.sort(key=lambda g: g.name.lower())
    emit(args, with_status(shown, state, games), "\n".join(game_line(g, state) for g in shown))


def cmd_find(ctx: Context, args) -> None:
    games = ctx.library()
    matches = recommend.find(games, " ".join(args.query))
    state = effective_state(games, storage.load_state(ctx.dir))
    emit(
        args,
        with_status(matches, state, games),
        "\n".join(game_line(g, state) for g in matches) or "no match",
    )


def mark_all_copies(ctx: Context, game: Game, status: str | None, note: str | None) -> list[str]:
    """A status applies to every copy of the game (same name on any store)."""
    keys = [g.key for g in ctx.library() if g.group == game.group] or [game.key]
    for key in keys:
        storage.set_status(ctx.dir, key, status, note)
    return keys


def cmd_mark(ctx: Context, args) -> None:
    game = resolve_game(ctx, args.game, args.name)
    status = None if args.status == "clear" else args.status
    keys = mark_all_copies(ctx, game, status, args.note)
    emit(
        args,
        {"status": "ok", "game": game.name, "key": game.key, "keys": keys, "mark": status},
        f"{game.name}: {status or 'cleared'} ({', '.join(keys)})",
    )


def cmd_dismiss(ctx: Context, args) -> None:
    key = f"{args.platform}:{args.external_id}"
    game = next((g for g in ctx.library() if g.key == key), None)
    if game:
        mark_all_copies(ctx, game, "dismissed", None)
    else:
        storage.set_status(ctx.dir, key, "dismissed")
    emit(
        args,
        {"status": "ok", "platform": args.platform, "external_id": args.external_id},
        f"Dismissed {args.platform}:{args.external_id}.",
    )


def cmd_queue(ctx: Context, args) -> None:
    state = storage.load_state(ctx.dir)
    by_key = {g.key: g for g in ctx.library()}
    rows = []
    seen: set[str] = set()
    for key, entry in sorted(state.items(), key=lambda kv: kv[1].get("updated") or ""):
        if entry["status"] in ("playing", "queued"):
            game = by_key.get(key)
            if game and game.group in seen:
                continue
            seen.add(game.group if game else key)
            rows.append(
                {
                    **(game.to_dict() if game else {"key": key}),
                    "status": entry["status"],
                    "note": entry.get("note"),
                }
            )
    emit(
        args,
        rows,
        "\n".join(f"{r['status']:<8} {r.get('name', r['key'])} [{r['key']}]" for r in rows)
        or "queue is empty",
    )


def cmd_stats(ctx: Context, args) -> None:
    games = ctx.library()
    state = effective_state(games, storage.load_state(ctx.dir))
    groups = {g.group for g in games}
    by_status: dict[str, int] = {}
    for group in groups:
        entry = next((state[g.key] for g in games if g.group == group and g.key in state), None)
        by_status[entry["status"] if entry else "unmarked"] = (
            by_status.get(entry["status"] if entry else "unmarked", 0) + 1
        )
    by_platform: dict[str, int] = {}
    for g in games:
        by_platform[g.platform] = by_platform.get(g.platform, 0) + 1
    meta = storage.load_meta(ctx.dir)
    refreshed = meta.get("refreshed_at")
    age = (datetime.now(UTC) - datetime.fromisoformat(refreshed)).days if refreshed else None
    result = {
        "status": "ok",
        "entries": len(games),
        "unique_games": len(groups),
        "by_platform": by_platform,
        "by_status": by_status,
        "times_known": sum(1 for g in games if g.main_hours is not None),
        "refreshed_at": refreshed,
        "age_days": age,
    }
    emit(
        args,
        result,
        f"{len(groups)} unique games ({len(games)} entries) {by_platform}\n{by_status}\nrefreshed: {refreshed or 'never'}",
    )


def cmd_deals(ctx: Context, args) -> None:
    api_key = ctx.env.get("ITAD_API_KEY")
    if not api_key:
        raise CliError(
            "ITAD_API_KEY is not set (get one at https://isthereanydeal.com/apps/my/; put it in the environment or <dir>/.env)"
        )
    try:
        if args.what == "bundles":
            owned = {deals.normalize(g.name) for g in ctx.library()}
            result = deals.bundles(api_key, owned, args.country, args.limit)
            text = "\n".join(
                f"{b['title']} ({b['store']}, expires {b['expiry'] or '?'})\n  not owned: {', '.join(b['not_owned']) or '-'}"
                for b in result
            )
            emit(args, result, text)
            return
        if not args.title and not args.appid:
            raise CliError("deals price needs --title or --appid")
        found = deals.price(api_key, args.title, args.appid, args.country, args.shop, args.on_sale)
    except deals.DealsError as exc:
        raise CliError(str(exc)) from exc
    if found is None:
        emit(args, {"status": "not_found", "query": args.title or args.appid}, "not found")
        return
    low = (found["historyLow"] or {}).get("all")
    lines = [found["title"]] + (
        [f"  all-time low: {low['amount']} {low['currency']}"] if low else []
    )
    lines += [
        f"  {d['shop']['name']}: {d['price']['amount']} {d['price']['currency']} (-{d['cut']}%)"
        for d in found["deals"]
    ]
    emit(args, {"status": "ok", **found}, "\n".join(lines))


def build_parser() -> argparse.ArgumentParser:
    common = argparse.ArgumentParser(add_help=False)
    common.add_argument("--json", action="store_true", help="machine-readable output")
    common.add_argument(
        "--dir", help="data directory (default $WHATTOPLAY_DIR or ~/.local/share/whattoplay)"
    )

    parser = argparse.ArgumentParser(
        prog="whattoplay",
        description="Pick what to play from the games you already own.",
        epilog=HELP_EPILOG,
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    parser.add_argument("--version", action="version", version=f"whattoplay {__version__}")
    sub = parser.add_subparsers(dest="command", required=True, metavar="command")

    def add(name, func, help_, **kw):
        p = sub.add_parser(name, parents=[common], help=help_, description=help_, **kw)
        p.set_defaults(func=func)
        return p

    add(
        "stores",
        cmd_stores,
        "List store backends (built-in and plugins) and whether they are ready",
    )
    p = add("configure", cmd_configure, "Set up a store interactively, or --enable/--disable it")
    p.add_argument("store")
    group = p.add_mutually_exclusive_group()
    group.add_argument("--enable", action="store_true")
    group.add_argument("--disable", action="store_true")
    p = add("refresh", cmd_refresh, "Fetch libraries from all enabled stores into the local cache")
    p.add_argument("--store", help="refresh only this store")
    p = add(
        "suggest", cmd_suggest, "Candidate pool of owned, barely-played games (not quality-ranked)"
    )
    p.add_argument("--threshold-minutes", type=int, default=120)
    p.add_argument("--limit", type=int, default=10)
    p.add_argument("--genre", action="append", help="only games with this genre (repeatable)")
    p.add_argument(
        "--exclude-genre", action="append", help="skip games with this genre (repeatable)"
    )
    p.add_argument(
        "--min-score", type=int, help="minimum Metacritic score (games without one are dropped)"
    )
    p.add_argument("--max-hours", type=float, help="main story at most this long (HowLongToBeat)")
    p.add_argument("--min-hours", type=float, help="main story at least this long (HowLongToBeat)")
    p.add_argument(
        "--lookup", type=int, default=25, help="max new HowLongToBeat lookups (default 25)"
    )
    p.add_argument(
        "--include-unknown-time", action="store_true", help="keep games without a known time"
    )
    p.add_argument("--platform")
    p.add_argument(
        "--shuffle", action="store_true", help="random order instead of least played first"
    )
    p.add_argument("--seed", type=int, help="reproducible shuffle")
    p = add("library", cmd_library, "Dump the cached library (no ranking or limit)")
    p.add_argument("--status", choices=storage.STATUSES, help="only games with this status")
    p.add_argument("--unmarked", action="store_true", help="only games without any status")
    p.add_argument("--platform")
    p = add("find", cmd_find, "Find games by name")
    p.add_argument("query", nargs="+")
    p = add(
        "mark", cmd_mark, "Set a game's status: playing, queued, finished, dismissed (or clear)"
    )
    p.add_argument("game", nargs="?", help="<platform>:<id>")
    p.add_argument("--name", help="match by name instead")
    p.add_argument("status", choices=[*storage.STATUSES, "clear"])
    p.add_argument("--note")
    p = add(
        "times",
        cmd_times,
        "Fetch HowLongToBeat times: for one game, or fill the cache for suggest candidates",
    )
    p.add_argument(
        "query", nargs="*", help="game name; omit to fill the cache for the candidate pool"
    )
    p.add_argument("--limit", type=int, default=25, help="max lookups (default 25)")
    p.add_argument("--threshold-minutes", type=int, default=120)
    p.add_argument("--refresh", action="store_true", help="look the named game up again")
    add("stats", cmd_stats, "Library size, status counts and when the library was last refreshed")
    add("queue", cmd_queue, "Games currently playing or queued")
    p = add("dismiss", cmd_dismiss, "Shorthand for `mark <platform>:<id> dismissed`")
    p.add_argument("platform")
    p.add_argument("external_id")
    p = add("deals", cmd_deals, "Prices and bundles from IsThereAnyDeal (needs ITAD_API_KEY)")
    p.add_argument("what", choices=["price", "bundles"])
    p.add_argument("--title")
    p.add_argument("--appid", type=int, help="Steam appid")
    p.add_argument("--country", default="US")
    p.add_argument("--shop", help="only deals from shops whose name contains this")
    p.add_argument("--on-sale", action="store_true", help="price: only currently discounted offers")
    p.add_argument("--limit", type=int, default=20)
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    try:
        args.func(Context(args), args)
    except CliError as exc:
        if args.json:
            print(json.dumps({"status": "error", "message": str(exc), **exc.extra}))
        else:
            print(f"error: {exc}", file=sys.stderr)
            for c in exc.extra.get("candidates", []):
                print(f"  {c['name']} [{c['key']}]", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
