"""
backend/automation_worker.py — Sequential institution automation.

Bridges the Refresh Orchestrator with existing InstitutionConnector
implementations. Runs institutions one at a time against a shared
Chrome instance, with support for:
  - Credential injection from the broker
  - Manual fallback (MFA, captchas, autofill clicks)
  - Transaction upsert to SQLite after each institution
"""

import logging
import time

from backend.result_writer import persist_connector_result, run_post_commit_pipeline
from extractors import get_connector

log = logging.getLogger("sentry.backend.worker")


def run_institution(
    institution_id: str,
    credentials: dict | None = None,
    *,
    refresh_run_id: str | None = None,
    **_kwargs,
) -> dict:
    """Run a full extraction for a single institution.

    This is the worker function passed to the orchestrator.

    Args:
        institution_id: e.g. "nfcu"
        credentials: {"username": "...", "password": "..."} or None
        refresh_run_id: Optional UUID of the orchestrator's refresh run.
            When passed, threaded into ``persist_connector_result`` so
            ``balance_snapshots.refresh_run_id`` and
            ``loan_details.refresh_run_id`` get populated for the
            current run (forensic linkage).
        **_kwargs: ignored. The orchestrator may pass forward-compatible
            keyword arguments; accept them silently rather than break.

    Returns:
        dict with keys: txn_inserted, txn_updated, txn_deleted,
                        balances_recorded, accounts_processed,
                        and (when applicable) mfa_prompted, anomalies,
                        failed_csvs.
    """
    start = time.time()
    log.info("Worker starting: %s", institution_id)

    connector = get_connector(institution_id)

    # Pass an isolated copy so the connector can't mutate the shared dict
    creds_copy = dict(credentials) if credentials else None

    result = connector.run(
        force=True,
        credentials=creds_copy,
    )

    # Clear the local copy immediately after use
    if creds_copy:
        for k in list(creds_copy):
            creds_copy[k] = ""
        creds_copy = None

    if result.status == "error":
        # Chain the original exception when connectors populate it, so
        # error_classifier in refresh_orchestrator can inspect the real
        # cause. Falls back to no chaining for legacy call sites that
        # only stash a string error.
        raise RuntimeError(
            f"Connector failed: {result.error or 'unknown error'}"
        ) from result.exception

    # ── Persist results to SQLite ─────────────────────────────
    summary = persist_connector_result(
        institution_id, result, refresh_run_id=refresh_run_id
    )

    # Propagate the MFA-prompted flag from the connector result so the
    # orchestrator can stamp refresh_events.mfa_prompted (AI-035).
    if getattr(result, "mfa_prompted", False):
        summary["mfa_prompted"] = True

    # ── Post-commit pipeline ──────────────────────────────────
    pipeline = run_post_commit_pipeline(institution_id)
    summary.update(pipeline)

    elapsed = time.time() - start
    summary["duration_seconds"] = elapsed
    log.info(
        "Worker completed: %s in %.1fs (+%d txns, %d balances)",
        institution_id,
        elapsed,
        summary["txn_inserted"],
        summary["balances_recorded"],
    )

    return summary
