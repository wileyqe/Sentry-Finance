"""
config.py — Loads config.yaml and exposes typed accessors.

Usage:
    from config import cfg
    cfg.excluded_categories   # ['Transfers', 'Savings', ...]
    cfg.data_sources          # list of dicts
    cfg.colors                # SimpleNamespace(dark_bg='#0f1117', ...)
"""
import pathlib, yaml
from types import SimpleNamespace

_BASE = pathlib.Path(__file__).resolve().parent
_CONFIG_PATH = _BASE / "config.yaml"

def _load():
    with open(_CONFIG_PATH, "r", encoding="utf-8") as f:
        return yaml.safe_load(f)

_raw = _load()


class Config:
    """Typed accessor for config.yaml values."""

    def __init__(self, raw: dict):
        self._raw = raw

    # ── Data Sources ──────────────────────────────────────────────────────
    @property
    def data_sources(self) -> list[dict]:
        return self._raw.get("data_sources", [])

    # ── Filter Logic ─────────────────────────────────────────────────────
    @property
    def excluded_categories(self) -> list[str]:
        return self._raw.get("excluded_categories", [])

    # ── Business Logic ───────────────────────────────────────────────────
    @property
    def officiating_pattern(self) -> str:
        return self._raw.get("officiating_pattern", "")

    @property
    def subscription_keywords(self) -> list[str]:
        return self._raw.get("subscription_keywords", [])

    @property
    def chase_keyword_map(self) -> dict[str, str]:
        return self._raw.get("chase_keyword_map", {})

    # ── Colors ───────────────────────────────────────────────────────────
    @property
    def colors(self) -> SimpleNamespace:
        c = self._raw.get("colors", {})
        return SimpleNamespace(**c)

    # ── Server ───────────────────────────────────────────────────────────
    @property
    def server_port(self) -> int:
        return self._raw.get("server", {}).get("port", 8050)

    @property
    def server_debug(self) -> bool:
        return self._raw.get("server", {}).get("debug", True)


cfg = Config(_raw)
