"""
extractors — Institution connector implementations.

CONNECTOR_REGISTRY is the single source of truth for all available
connectors. Both run_all.py and automation_worker.py use this to
look up connectors by institution ID — no more diverging if/elif chains.

Each entry is a factory lambda that lazily imports the connector class
to avoid pulling Playwright into every process that imports this package.

To add a new institution:
  1. Create extractors/<name>_connector.py implementing InstitutionConnector
  2. Add an entry to CONNECTOR_REGISTRY below
  3. Add the institution to accounts.yaml
"""

import importlib
import logging

log = logging.getLogger("sentry.extractors")


def _lazy(module: str, cls: str, headless: bool = False):
    """Lazily import a connector class to avoid loading Playwright at module level."""
    mod = importlib.import_module(module)
    return getattr(mod, cls)(headless=headless)


# Single authoritative connector registry.
# connectors run SEQUENTIALLY — never in parallel — to avoid CDP port conflicts.
# See: resource-session-management.md § No Concurrent Sprawl
CONNECTOR_REGISTRY: dict[str, callable] = {
    "nfcu":     lambda: _lazy("extractors.nfcu_connector",     "NFCUConnector"),
    "chase":    lambda: _lazy("extractors.chase_connector",    "ChaseConnector"),
    "fidelity": lambda: _lazy("extractors.fidelity_connector", "FidelityConnector"),
    "acorns":   lambda: _lazy("extractors.acorns_connector",   "AcornsConnector"),
    "affirm":   lambda: _lazy("extractors.affirm_connector",   "AffirmConnector"),
    # "tsp":    lambda: _lazy("extractors.tsp_connector",      "TSPConnector"),
}


def get_connector(institution_id: str, headless: bool = False):
    """Return an instantiated connector for the given institution ID.

    Raises ValueError if no connector is registered.
    """
    factory = CONNECTOR_REGISTRY.get(institution_id)
    if factory is None:
        registered = ", ".join(CONNECTOR_REGISTRY)
        raise ValueError(
            f"No connector registered for '{institution_id}'. "
            f"Available: {registered}"
        )
    return factory()


# ── Convenience re-exports for direct imports ────────────────────────────────
# These remain so that `from extractors import NFCUConnector` still works.

from extractors.nfcu_connector import NFCUConnector       # noqa: E402, F401
from extractors.chase_connector import ChaseConnector     # noqa: E402, F401
from extractors.acorns_connector import AcornsConnector   # noqa: E402, F401
from extractors.fidelity_connector import FidelityConnector  # noqa: E402, F401

__all__ = [
    "CONNECTOR_REGISTRY",
    "get_connector",
    "NFCUConnector",
    "ChaseConnector",
    "AcornsConnector",
    "FidelityConnector",
]
