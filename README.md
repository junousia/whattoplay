# whattoplay

Pick what to play from the games you already own. `whattoplay` keeps one cached library from any number of store backends (Steam and Epic built in, anything else as a plugin), tracks what you are playing, queued, finished or dismissed, and looks up prices and bundles. Output is plain text or JSON, so it works equally well from a terminal and as a tool for an AI agent (`SKILL.md` is the agent-facing guide, in the [Agent Skills](https://agentskills.io) format).

The tool filters and sorts; choosing a good recommendation is left to you or your agent.

## Install

```bash
uvx whattoplay --help                 # no install
uv tool install whattoplay            # or install it
uv tool install 'whattoplay[epic,hltb]'    # with Epic support (legendary) and HowLongToBeat times
```

Python 3.11 or newer.

## Set up a store

```bash
whattoplay stores                  # what exists, what is enabled, what is missing
whattoplay configure steam         # asks for your Steam Web API key and SteamID64 / profile name
whattoplay configure epic --enable # Epic: `pip install 'whattoplay[epic]'` and run `legendary auth` first
whattoplay refresh                 # fetch every enabled, configured store
```

Settings are resolved per store from environment variables (also read from `<data dir>/.env`, created with mode 600) and, for non-secret values, from `<data dir>/config.toml`:

```toml
[stores.steam]
steam_id64 = "76561198000000000"

[stores.epic]
enabled = false
```

Secrets (API keys, tokens) are only ever read from the environment, never from `config.toml`. A store that fails to refresh is reported and keeps its previously cached games; the other stores still refresh.

The data directory is `--dir`, else `$WHATTOPLAY_DIR`, else `~/.local/share/whattoplay`.

## Use

```bash
whattoplay suggest --limit 20 --genre puzzle     # barely-played games, least played first
whattoplay suggest --min-score 80 --exclude-genre horror --shuffle
whattoplay suggest --max-hours 6                 # short games: looks times up on HowLongToBeat as needed
whattoplay times "Portal 2"                      # time to beat for one game
whattoplay stats                                  # counts and when the library was last refreshed
whattoplay find portal
whattoplay mark steam:620 playing
whattoplay mark --name "Portal 2" finished --note "great"
whattoplay mark epic:Hibiscus dismissed
whattoplay queue                                  # playing + queued
whattoplay library --unmarked --platform steam
whattoplay deals price --title "Hades" --country FI --shop steam   # needs ITAD_API_KEY; add --on-sale for discounted offers only
whattoplay deals bundles --limit 10               # flags games you don't own yet
```

A game owned on several stores counts once everywhere: marks apply to all copies, and genres or scores missing on one store are borrowed from another. Add `--json` to any command. Games are addressed as `<platform>:<id>` or with `--name`.

Time-to-beat data comes from [HowLongToBeat](https://howlongtobeat.com), which has no official API: this uses the unofficial [`howlongtobeatpy`](https://github.com/ScrappyCocco/HowLongToBeat-PythonAPI) scraper (`whattoplay[hltb]`), so it can break when the site changes. Lookups are one at a time, about a second apart, capped per call (`--lookup`) and cached, so each game is requested at most once. Please keep it that way.

Deals use [IsThereAnyDeal](https://isthereanydeal.com/apps/my/) (free API key in `ITAD_API_KEY`).

## Writing a store plugin

A store is a subclass of `whattoplay.stores.base.Store` with a `name`, declared `settings` and a `fetch_library()` that returns `Game` objects. Optionally implement `enrich()` (genres, scores, cover art, with a persistent cache) and `store_url()`.

Two ways to ship one:

1. **Local file:** copy [`examples/example_store.py`](examples/example_store.py) to `<data dir>/plugins/`. It is picked up on the next run.
2. **Package:** register the class as an entry point and `pip install` it:

   ```toml
   [project.entry-points."whattoplay.stores"]
   psn = "whattoplay_psn:PsnStore"
   ```

A plugin that fails to import is reported by `whattoplay stores` and never stops the others. Plugins run with your user's permissions, so only install ones you trust.

A PlayStation backend, for example, would implement `fetch_library()` on top of an existing client library such as [`psnawp`](https://github.com/isFakeAccount/psnawp), read its token from a `PSN_NPSSO` environment variable (declared as a secret `Setting`), and map trophy/play-time data to `Game`. A ready-made PlayStation plugin lives in [whattoplay-psn](https://github.com/junousia/whattoplay-psn) (`uv tool install whattoplay --with whattoplay-psn`).

## Using it as an agent skill

Copy or symlink this repository into your agent's skills directory (for Hermes, `~/.hermes/skills/games/whattoplay`). Your personal taste and rules (genres to avoid, store restrictions, how readily to recommend purchases) belong in `<data dir>/preferences.md`, which the skill tells the agent to read, so nothing personal ends up in the repository.

## Development

```bash
uv sync
uv run pytest
uv run ruff check src tests
```

## License

MIT
