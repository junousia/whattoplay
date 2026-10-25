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

    shutil.copy(Path(__file__).parent.parent / "examples" / "example_store.py", data_dir / "plugins" / "jsonfile.py")
    (data_dir / "games.json").write_text(json.dumps([{"id": 7, "name": "Example", "minutes": 12}]))
    (data_dir / ".env").write_text(f"FAKE_TOKEN=ok\nWHATTOPLAY_JSONFILE_PATH={data_dir / 'games.json'}\n")
    code, out = run("refresh", "--store", "jsonfile")
    assert code == 0 and out["stores"]["jsonfile"] == {"status": "ok", "count": 1}
    _, found = run("find", "example")
    assert found[0]["key"] == "jsonfile:7"
