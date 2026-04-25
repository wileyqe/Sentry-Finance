"""
v39: Dedupe ``derived_summaries`` rows where ``period IS NULL``.

The ``UNIQUE(scope, metric, period)`` constraint on ``derived_summaries``
treats NULL period values as distinct (SQLite's standard NULL-handling
in unique constraints), so every recompute-pipeline run that writes
metrics like ``net_worth``, ``emergency_fund_months``, ``interest_earned``,
or the ``nw_*`` velocity series accumulates a fresh duplicate row.

This migration:
  1. Collapses existing duplicate NULL-period rows to the most recent
     per ``(scope, metric)`` (highest ``id`` wins; ``computed_at`` ties
     are broken by ``id``).
  2. Adds a partial unique index that catches future NULL-period dupes
     so the writers' ``ON CONFLICT`` clauses (updated alongside this
     migration) can upsert correctly.

Idempotent: ``CREATE UNIQUE INDEX IF NOT EXISTS`` and the cleanup DELETE
is a no-op when no dupes exist.
"""

VERSION = 39


def run(conn):
    # 1. Cleanup: keep the highest-id row per (scope, metric) for NULL-period rows.
    conn.execute(
        """
        DELETE FROM derived_summaries
        WHERE period IS NULL
          AND id NOT IN (
              SELECT MAX(id) FROM derived_summaries
              WHERE period IS NULL
              GROUP BY scope, metric
          )
        """
    )

    # 2. Partial unique index: prevents future NULL-period duplicates
    # and lets ON CONFLICT(scope, metric) WHERE period IS NULL upsert.
    conn.execute(
        """
        CREATE UNIQUE INDEX IF NOT EXISTS idx_derived_summaries_null_period
            ON derived_summaries(scope, metric)
            WHERE period IS NULL
        """
    )
