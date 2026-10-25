"""Data directory, `.env` secrets and the per-store `config.toml`."""

from __future__ import annotations

import os
import tomllib
from collections.abc import Mapping
from pathlib import Path

ENV_DIR = "WHATTOPLAY_DIR"


def resolve_data_dir(override: str | None = None) -> Path:
    if override:
        return Path(override).expanduser()
    if os.environ.get(ENV_DIR):
        return Path(os.environ[ENV_DIR]).expanduser()
    base = os.environ.get("XDG_DATA_HOME") or str(Path.home() / ".local" / "share")
    return Path(base) / "whattoplay"


def parse_env_file(path: Path) -> dict[str, str]:
    values: dict[str, str] = {}
    if not path.exists():
        return values
    for raw in path.read_text().splitlines():
        line = raw.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, _, value = line.partition("=")
        values[key.strip()] = value.strip().strip("'\"")
    return values


def load_env(data_dir: Path, environ: Mapping[str, str] | None = None) -> dict[str, str]:
    """Process environment wins over `<data_dir>/.env`."""
    merged = parse_env_file(data_dir / ".env")
    merged.update(os.environ if environ is None else environ)
    return merged


def load_config(data_dir: Path) -> dict:
    path = data_dir / "config.toml"
    if not path.exists():
        return {}
    return tomllib.loads(path.read_text())


def _toml_value(value: object) -> str:
    if isinstance(value, bool):
        return "true" if value else "false"
    if isinstance(value, int):
        return str(value)
    escaped = str(value).replace("\\", "\\\\").replace('"', '\\"')
    return f'"{escaped}"'


def save_config(data_dir: Path, config: dict) -> None:
    """Writes the flat `[stores.<name>]` tables this tool uses (not a general TOML writer)."""
    lines: list[str] = []
    for name, table in sorted(config.get("stores", {}).items()):
        lines.append(f"[stores.{name}]")
        lines.extend(f"{k} = {_toml_value(v)}" for k, v in table.items())
        lines.append("")
    data_dir.mkdir(parents=True, exist_ok=True)
    (data_dir / "config.toml").write_text("\n".join(lines))


def update_env_file(data_dir: Path, values: Mapping[str, str]) -> None:
    """Upserts KEY=value lines in `<data_dir>/.env` and keeps the file private (0600)."""
    path = data_dir / ".env"
    data_dir.mkdir(parents=True, exist_ok=True)
    lines = path.read_text().splitlines() if path.exists() else []
    seen: set[str] = set()
    out: list[str] = []
    for line in lines:
        key = line.split("=", 1)[0].strip() if "=" in line else None
        if key in values:
            out.append(f"{key}={values[key]}")
            seen.add(key)
        else:
            out.append(line)
    out.extend(f"{k}={v}" for k, v in values.items() if k not in seen)
    path.write_text("\n".join(out) + "\n")
    path.chmod(0o600)
