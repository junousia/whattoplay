from __future__ import annotations

from whattoplay.models import Game
from whattoplay.stores.base import Store, StoreError


class EpicStore(Store):
    """Epic Games Store via `legendary` (`pip install whattoplay[epic]`, then `legendary auth`)."""

    name = "epic"
    label = "Epic Games Store"

    def _core(self):
        try:
            from legendary.core import LegendaryCore
        except ImportError as exc:
            raise StoreError("legendary is not installed (pip install 'whattoplay[epic]')") from exc
        return LegendaryCore()

    def missing(self) -> list[str]:
        try:
            import legendary.core  # noqa: F401
        except ImportError:
            return ["legendary is not installed (pip install 'whattoplay[epic]')"]
        return []

    def fetch_library(self) -> list[Game]:
        core = self._core()
        try:
            logged_in = core.login()
        except ValueError as exc:
            raise StoreError(
                "legendary has no saved Epic login; run `legendary auth` first"
            ) from exc
        if not logged_in:
            raise StoreError(
                "legendary's saved Epic login is no longer valid; run `legendary auth` again"
            )
        return [
            Game(
                name=g.app_title, platform=self.name, external_id=g.app_name, playtime_minutes=None
            )
            for g in core.get_game_list(update_assets=True)
        ]
