"""Store discovery: built-ins, installed plugins (entry points) and local plugin files."""

from __future__ import annotations

import importlib.util
import sys
from collections.abc import Mapping
from importlib.metadata import entry_points
from pathlib import Path

from whattoplay.stores.base import Setting, Store, StoreError
from whattoplay.stores.epic import EpicStore
from whattoplay.stores.steam import SteamStore

__all__ = ["Setting", "Store", "StoreError", "build_stores", "discover"]

ENTRY_POINT_GROUP = "whattoplay.stores"


def _is_store(obj: object) -> bool:
    return isinstance(obj, type) and issubclass(obj, Store) and obj is not Store and bool(obj.name)


def _load_plugin_file(path: Path) -> list[type[Store]]:
    spec = importlib.util.spec_from_file_location(f"whattoplay_plugin_{path.stem}", path)
    if spec is None or spec.loader is None:
        return []
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    declared = getattr(module, "STORES", None)
    return [
        c for c in (declared if declared is not None else vars(module).values()) if _is_store(c)
    ]


def discover(data_dir: Path) -> tuple[dict[str, type[Store]], list[str]]:
    """Returns (store classes by name, load errors). A broken plugin never hides the others."""
    classes: dict[str, type[Store]] = {c.name: c for c in (SteamStore, EpicStore)}
    errors: list[str] = []
    for ep in entry_points(group=ENTRY_POINT_GROUP):
        try:
            loaded = ep.load()
            for cls in loaded if isinstance(loaded, (list, tuple)) else [loaded]:
                if _is_store(cls):
                    classes[cls.name] = cls
        except Exception as exc:  # noqa: BLE001 - plugin code is third-party
            errors.append(f"plugin {ep.name}: {exc}")
    plugin_dir = data_dir / "plugins"
    for path in sorted(plugin_dir.glob("*.py")) if plugin_dir.is_dir() else []:
        try:
            for cls in _load_plugin_file(path):
                classes[cls.name] = cls
        except Exception as exc:  # noqa: BLE001
            errors.append(f"plugin file {path.name}: {exc}")
    return classes, errors


def build_stores(
    data_dir: Path, config: Mapping[str, object], env: Mapping[str, str]
) -> tuple[dict[str, Store], list[str]]:
    classes, errors = discover(data_dir)
    tables = config.get("stores", {}) if isinstance(config.get("stores"), dict) else {}
    return {name: cls(tables.get(name, {}), env) for name, cls in classes.items()}, errors
