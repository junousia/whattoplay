"""Template for a local store plugin.

Copy to `<data dir>/plugins/<anything>.py` (default data dir: ~/.local/share/whattoplay) and
`whattoplay stores` lists it. To ship it as an installable package instead, expose the class
through an entry point in your pyproject.toml:

    [project.entry-points."whattoplay.stores"]
    mystore = "my_package:MyStore"

This one reads a plain JSON file so it needs no account; a real plugin calls the store's API
in `fetch_library` (for example PlayStation via the `psnawp` package) and raises `StoreError`
with a short, user-readable message when the call fails.
"""

import json
from pathlib import Path

from whattoplay.models import Game
from whattoplay.stores.base import Setting, Store, StoreError


class JsonFileStore(Store):
    name = "jsonfile"  # the platform name shown on every game: "jsonfile:<external_id>"
    label = "Games from a JSON file"
    settings = (
        # Non-secret: set in config.toml under [stores.jsonfile], or via the env var.
        Setting("path", "WHATTOPLAY_JSONFILE_PATH", "Path to a JSON list of {id, name, minutes}"),
        # Secrets (secret=True) are only ever read from the environment / <data dir>/.env.
        # Setting("token", "MYSTORE_TOKEN", "API token", secret=True),
    )

    def fetch_library(self) -> list[Game]:
        try:
            items = json.loads(Path(self.value("path")).read_text())
        except (OSError, ValueError) as exc:
            raise StoreError(f"could not read {self.value('path')}: {exc}") from exc
        return [
            Game(
                name=item["name"],
                platform=self.name,
                external_id=str(item["id"]),
                playtime_minutes=item.get("minutes"),  # None when the store has no playtime
            )
            for item in items
        ]

    def store_url(self, game: Game) -> str | None:
        return None  # return the store page URL when there is one; agents link to it


STORES = [JsonFileStore]  # optional: lists exactly which classes to register
