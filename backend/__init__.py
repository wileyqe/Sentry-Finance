"""
backend — Backend server and orchestration layer for Sentry Finance.

Components:
  - api_server:           FastAPI serving data from SQLite
  - refresh_orchestrator: Staleness evaluation and coordination
  - credential_broker:    Elevated subprocess for Windows Hello
  - automation_worker:    Sequential institution automation
  - state_machine:        Refresh state definitions and transitions
"""

