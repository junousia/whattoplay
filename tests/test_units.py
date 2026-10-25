import requests_mock

from whattoplay import deals, recommend, storage
from whattoplay.config import load_config, load_env, parse_env_file, save_config, update_env_file
from whattoplay.models import Game
from whattoplay.stores.steam import SteamStore, fetch_app_metadata, resolve_steam_id


def g(name, platform, pid, minutes, genres=()):
    return Game(name, platform, pid, minutes, list(genres))


def test_suggest_orders_least_played_first_unknown_last():
    games = [g("B", "steam", "2", 60), g("A", "steam", "1", 0), g("U", "epic", "3", None)]
    names = [x.name for x in recommend.suggest(games, limit=10)]
    assert names == ["A", "B", "U"]


def test_suggest_balances_platforms():
    games = [g(f"S{i}", "steam", str(i), i) for i in range(6)] + [
        g(f"E{i}", "epic", str(i), None) for i in range(3)
    ]
    picks = recommend.suggest(games, limit=4)
    assert {x.platform for x in picks} == {"steam", "epic"}


def test_suggest_filters_genre_platform_and_excluded():
    games = [
        g("A", "steam", "1", 0, ["RPG"]),
        g("B", "steam", "2", 0, ["Puzzle"]),
        g("C", "epic", "3", None, ["RPG"]),
    ]
    assert [x.name for x in recommend.suggest(games, genres=["rpg"], exclude={"epic:3"})] == ["A"]
    assert [x.name for x in recommend.suggest(games, platform="epic")] == ["C"]


def test_find_prefers_exact_match():
    games = [g("Portal", "steam", "1", 0), g("Portal 2", "steam", "2", 0)]
    assert [x.name for x in recommend.find(games, "portal")] == ["Portal"]
    assert len(recommend.find(games, "port")) == 2


def test_state_roundtrip_and_validation(tmp_path):
    storage.set_status(tmp_path, "steam:1", "queued", "later")
    assert storage.load_state(tmp_path)["steam:1"]["note"] == "later"
    storage.set_status(tmp_path, "steam:1", None)
    assert storage.load_state(tmp_path) == {}
    try:
        storage.set_status(tmp_path, "steam:1", "bogus")
    except ValueError:
        pass
    else:
        raise AssertionError("invalid status accepted")


def test_game_from_dict_ignores_unknown_keys():
    assert (
        Game.from_dict({"name": "X", "platform": "steam", "external_id": "1", "legacy": 1}).name
        == "X"
    )


def test_env_precedence_and_permissions(tmp_path):
    update_env_file(tmp_path, {"A": "1"})
    update_env_file(tmp_path, {"A": "2", "B": "3"})
    assert parse_env_file(tmp_path / ".env") == {"A": "2", "B": "3"}
    assert (tmp_path / ".env").stat().st_mode & 0o777 == 0o600
    assert load_env(tmp_path, {"A": "from-env"})["A"] == "from-env"


def test_config_roundtrip(tmp_path):
    save_config(tmp_path, {"stores": {"steam": {"steam_id64": "7656", "enabled": True}}})
    assert load_config(tmp_path)["stores"]["steam"] == {"steam_id64": "7656", "enabled": True}


def test_steam_owned_games_and_missing_settings():
    store = SteamStore({"steam_id64": "7656"}, {"STEAM_API_KEY": "k"})
    assert store.missing() == []
    assert SteamStore({}, {}).missing()
    with requests_mock.Mocker() as m:
        m.get(
            "https://api.steampowered.com/IPlayerService/GetOwnedGames/v0001/",
            json={
                "response": {"games": [{"appid": 620, "name": "Portal 2", "playtime_forever": 5}]}
            },
        )
        [game] = store.fetch_library()
    assert game.key == "steam:620" and game.store_url.endswith("/app/620/")


def test_steam_secret_never_read_from_config_file():
    store = SteamStore({"api_key": "leaked"}, {})
    assert store.value("api_key") is None


def test_steam_metadata_unknown_is_none_not_cached_empty():
    with requests_mock.Mocker() as m:
        m.get("https://store.steampowered.com/api/appdetails", json={"620": {"success": False}})
        assert fetch_app_metadata("620") is None
        m.get(
            "https://store.steampowered.com/api/appdetails",
            json={
                "620": {
                    "success": True,
                    "data": {"genres": [{"description": "Puzzle"}], "metacritic": {"score": 95}},
                }
            },
        )
        assert fetch_app_metadata("620")["metacritic_score"] == 95


def test_resolve_steam_id_variants():
    assert (
        resolve_steam_id("k", "https://steamcommunity.com/profiles/76561198000000000/")
        == "76561198000000000"
    )
    with requests_mock.Mocker() as m:
        m.get(
            "https://api.steampowered.com/ISteamUser/ResolveVanityURL/v0001/",
            json={"response": {"success": 1, "steamid": "76561198000000001"}},
        )
        assert resolve_steam_id("k", "https://steamcommunity.com/id/someone") == "76561198000000001"


def test_bundles_flags_owned_games():
    payload = [
        {
            "title": "B",
            "page": {"name": "Humble"},
            "url": "u",
            "expiry": None,
            "tiers": [{"games": [{"title": "Portal 2"}, {"title": "New Game"}]}],
        }
    ]
    with requests_mock.Mocker() as m:
        m.get("https://api.isthereanydeal.com/bundles/v1", json=payload)
        [b] = deals.bundles("k", {deals.normalize("Portal: 2")}, "FI", 5)
    assert b["not_owned"] == ["New Game"]


def test_epic_metadata_comes_from_exact_steam_name_match():
    from whattoplay.stores.epic import EpicStore

    games = [g("Hades", "epic", "e1", None), g("Epic Exclusive", "epic", "e2", None)]
    with requests_mock.Mocker() as m:
        m.get(
            "https://store.steampowered.com/api/storesearch/",
            [
                {
                    "json": {
                        "items": [
                            {"type": "app", "id": 1145360, "name": "Hades"},
                            {"type": "app", "id": 9, "name": "Hades II"},
                        ]
                    }
                },
                {"json": {"items": []}},
            ],
        )
        m.get(
            "https://store.steampowered.com/api/appdetails",
            json={
                "1145360": {
                    "success": True,
                    "data": {"genres": [{"description": "Action"}], "metacritic": {"score": 93}},
                }
            },
        )
        cache: dict = {}
        from whattoplay.stores import epic

        epic.METADATA_DELAY_SECONDS = 0
        EpicStore({}, {}).enrich(games, cache, lambda _msg: None)
    assert games[0].genres == ["Action"] and games[0].metacritic_score == 93
    assert games[1].genres == [] and cache["e2"] == {}  # miss is cached so it is not re-queried


def test_price_lists_all_current_prices_unless_on_sale_requested():
    entry = [
        {
            "id": "g1",
            "historyLow": {"all": {"amount": 6.1, "currency": "EUR"}},
            "deals": [
                {"shop": {"name": "Steam"}, "price": {"amount": 20, "currency": "EUR"}, "cut": 0}
            ],
        }
    ]
    with requests_mock.Mocker() as m:
        m.get(
            "https://api.isthereanydeal.com/games/lookup/v1",
            json={"found": True, "game": {"id": "g1", "title": "Hades"}},
        )
        prices = m.post("https://api.isthereanydeal.com/games/prices/v3", json=entry)
        full = deals.price("k", "Hades", None, "FI")
        assert "deals" not in prices.last_request.qs  # `deals=true` would hide undiscounted offers
        deals.price("k", "Hades", None, "FI", on_sale=True)
        assert prices.last_request.qs["deals"] == ["true"]
    assert full["deals"][0]["cut"] == 0 and full["historyLow"]["all"]["amount"] == 6.1
