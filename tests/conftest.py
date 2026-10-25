import json

import pytest

PLUGIN = """
from whattoplay.models import Game
from whattoplay.stores.base import Setting, Store, StoreError


class FakeStore(Store):
    name = "fake"
    label = "Fake Store"
    settings = (Setting("token", "FAKE_TOKEN", "Fake token", secret=True),)

    def fetch_library(self):
        if self.value("token") == "bad":
            raise StoreError("bad token")
        return [
            Game("Portal", "fake", "1", playtime_minutes=0),
            Game("Portal 2", "fake", "2", playtime_minutes=30),
            Game("Hades", "fake", "3", playtime_minutes=500, genres=["Roguelike"]),
        ]

    def store_url(self, game):
        return f"https://fake.example/{game.external_id}"
"""


@pytest.fixture
def data_dir(tmp_path, monkeypatch):
    d = tmp_path / "data"
    (d / "plugins").mkdir(parents=True)
    (d / "plugins" / "fake.py").write_text(PLUGIN)
    (d / "config.toml").write_text(
        "[stores.steam]\nenabled = false\n[stores.epic]\nenabled = false\n"
    )
    (d / ".env").write_text("FAKE_TOKEN=ok\n")
    monkeypatch.delenv("FAKE_TOKEN", raising=False)
    monkeypatch.delenv("ITAD_API_KEY", raising=False)
    return d


@pytest.fixture
def run(data_dir, capsys):
    from whattoplay.cli import main

    def _run(*argv):
        code = main([*argv, "--dir", str(data_dir), "--json"])
        out = capsys.readouterr().out.strip()
        return code, (json.loads(out) if out else None)

    return _run
