def test_stores_lists_plugin_and_builtins(run):
    code, out = run("stores")
    names = {s["name"]: s for s in out["stores"]}
    assert code == 0 and {"steam", "epic", "fake"} <= set(names)
    assert names["fake"]["ready"] and not names["steam"]["enabled"]


def test_refresh_then_suggest_and_status_flow(run):
    code, out = run("refresh")
    assert code == 0 and out["stores"]["fake"] == {"status": "ok", "count": 3}

    _, picks = run("suggest")
    assert [g["name"] for g in picks] == ["Portal", "Portal 2"]  # Hades is over the threshold
    assert picks[0]["store_url"] == "https://fake.example/1"

    assert run("mark", "fake:1", "finished", "--note", "loved it")[0] == 0
    assert run("mark", "--name", "hades", "queued")[0] == 0
    _, picks = run("suggest")
    assert [g["name"] for g in picks] == ["Portal 2"]  # finished games are not suggested again

    _, queue = run("queue")
    assert [(q["name"], q["status"]) for q in queue] == [("Hades", "queued")]
    _, finished = run("library", "--status", "finished")
    assert finished[0]["note"] == "loved it"

    run("mark", "fake:1", "clear")
    _, picks = run("suggest")
    assert "Portal" in [g["name"] for g in picks]


def test_ambiguous_name_lists_candidates(run):
    run("refresh")
    code, out = run("mark", "--name", "portal 2x", "finished")
    assert code == 1 and "matches" in out["message"]
    run("find", "portal")
    code, out = run("mark", "--name", "Portal", "dismissed")  # exact match beats substring
    assert code == 0 and out["key"] == "fake:1"
    code, out = run("mark", "--name", "por", "dismissed")
    assert code == 1 and len(out["candidates"]) == 2


def test_failing_store_keeps_cached_games(run, data_dir):
    run("refresh")
    (data_dir / ".env").write_text("FAKE_TOKEN=bad\n")
    code, out = run("refresh")
    assert code == 1 and out["stores"]["fake"]["status"] == "error"
    _, games = run("library")
    assert len(games) == 3


def test_refresh_skips_unconfigured_store(run, data_dir):
    (data_dir / "config.toml").write_text("")
    code, out = run("refresh")
    assert code == 0
    assert out["stores"]["steam"]["status"] == "skipped"
    assert out["stores"]["fake"]["status"] == "ok"


def test_legacy_dismissed_file_is_honoured(run, data_dir):
    run("refresh")
    (data_dir / "dismissed.json").write_text('[{"platform": "fake", "external_id": "2"}]')
    _, picks = run("suggest")
    assert [g["name"] for g in picks] == ["Portal"]


def test_suggest_without_library(run):
    code, out = run("suggest")
    assert code == 0 and out["status"] == "empty"


def test_deals_needs_key(run):
    code, out = run("deals", "bundles")
    assert code == 1 and "ITAD_API_KEY" in out["message"]


def test_broken_plugin_is_reported_not_fatal(run, data_dir):
    (data_dir / "plugins" / "broken.py").write_text("raise RuntimeError('boom')")
    code, out = run("stores")
    assert code == 0 and any("boom" in e for e in out["plugin_errors"])


def test_example_plugin_loads_and_refreshes(run, data_dir):
    import json
    import shutil
    from pathlib import Path

    shutil.copy(
        Path(__file__).parent.parent / "examples" / "example_store.py",
        data_dir / "plugins" / "jsonfile.py",
    )
    (data_dir / "games.json").write_text(json.dumps([{"id": 7, "name": "Example", "minutes": 12}]))
    (data_dir / ".env").write_text(
        f"FAKE_TOKEN=ok\nWHATTOPLAY_JSONFILE_PATH={data_dir / 'games.json'}\n"
    )
    code, out = run("refresh", "--store", "jsonfile")
    assert code == 0 and out["stores"]["jsonfile"] == {"status": "ok", "count": 1}
    _, found = run("find", "example")
    assert found[0]["key"] == "jsonfile:7"


def _two_store_library(data_dir):
    """Portal on two stores: the second copy has no playtime and no metadata."""
    import json

    games = [
        {
            "name": "Portal",
            "platform": "fake",
            "external_id": "1",
            "playtime_minutes": 700,
            "genres": ["Puzzle"],
            "metacritic_score": 90,
        },
        {"name": "Portal", "platform": "other", "external_id": "x", "playtime_minutes": None},
        {
            "name": "Hades",
            "platform": "fake",
            "external_id": "3",
            "playtime_minutes": 0,
            "genres": ["Roguelike"],
            "metacritic_score": 93,
        },
        {
            "name": "Gloomhaven",
            "platform": "other",
            "external_id": "y",
            "playtime_minutes": None,
            "genres": ["Strategy"],
        },
    ]
    (data_dir / "library.json").write_text(json.dumps(games))


def test_same_game_on_two_stores_counts_once_and_uses_largest_playtime(run, data_dir):
    _two_store_library(data_dir)
    _, picks = run("suggest")
    assert sorted(g["name"] for g in picks) == [
        "Gloomhaven",
        "Hades",
    ]  # Portal is played on one store


def test_mark_applies_to_every_copy(run, data_dir):
    _two_store_library(data_dir)
    code, out = run("mark", "--name", "portal", "finished")
    assert code == 0 and sorted(out["keys"]) == ["fake:1", "other:x"]
    _, found = run("find", "portal")
    assert [(g["status"], g["also_on"]) for g in found] == [
        ("finished", ["other:x"]),
        ("finished", ["fake:1"]),
    ]
    run("mark", "fake:1", "clear")
    _, found = run("find", "portal")
    assert all(g["status"] is None for g in found)


def test_suggest_filters_and_shuffle(run, data_dir):
    _two_store_library(data_dir)
    _, picks = run("suggest", "--min-score", "92")
    assert [g["name"] for g in picks] == ["Hades"]
    _, picks = run("suggest", "--exclude-genre", "roguelike")
    assert [g["name"] for g in picks] == ["Gloomhaven"]
    _, a = run("suggest", "--seed", "1")
    _, b = run("suggest", "--seed", "1")
    assert a == b


def test_stats_counts_games_once(run, data_dir):
    _two_store_library(data_dir)
    run("mark", "--name", "portal", "finished")
    _, out = run("stats")
    assert out["unique_games"] == 3 and out["entries"] == 4
    assert out["by_status"] == {"finished": 1, "unmarked": 2}
    assert out["refreshed_at"] is None


def test_refresh_shares_metadata_and_records_time(run, data_dir):
    from whattoplay import storage
    from whattoplay.models import Game

    games = [Game("A", "p1", "1", 0, ["RPG"], 80), Game("A", "p2", "2", 0)]
    storage.share_metadata(games)
    assert games[1].genres == ["RPG"] and games[1].metacritic_score == 80
    run("refresh")
    assert run("stats")[1]["refreshed_at"]
