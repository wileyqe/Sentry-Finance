from __future__ import annotations

import pytest
from fastapi import HTTPException


def test_start_refresh_passes_targeted_request_to_session(monkeypatch):
    from backend.routers import refresh as refresh_router

    captured = {}

    class ImmediateThread:
        def __init__(self, target, daemon):
            self.target = target
            self.daemon = daemon

        def start(self):
            self.target()

    class FakeSession:
        def __init__(self, trigger, target_institutions=None, force=False):
            captured["session"] = {
                "trigger": trigger,
                "target_institutions": target_institutions,
                "force": force,
            }

        def on_event(self, callback):
            captured["callback"] = callback

        def run(self, worker_fn=None):
            captured["worker_fn"] = worker_fn
            return {"status": "success", "institutions": {"mypay": {}}}

    events = []

    monkeypatch.setattr(refresh_router.threading, "Thread", ImmediateThread)
    monkeypatch.setattr(refresh_router, "RefreshSession", FakeSession)
    monkeypatch.setattr(
        refresh_router,
        "broadcast_event",
        lambda kind, data: events.append((kind, data)),
    )

    response = refresh_router.start_refresh(
        refresh_router.RefreshStartRequest(
            trigger="manual_sync",
            institutions=[" MYPAY ", "mypay"],
            force=True,
        )
    )

    assert response == {
        "status": "started",
        "trigger": "manual_sync",
        "institutions": ["mypay"],
        "force": True,
    }
    assert captured["session"] == {
        "trigger": "manual_sync",
        "target_institutions": ["mypay"],
        "force": True,
    }
    assert events[-1][0] == refresh_router.sse_topics.REFRESH_COMPLETE
    assert events[-1][1]["status"] == "success"


def test_start_refresh_rejects_unknown_target():
    from backend.routers import refresh as refresh_router

    with pytest.raises(HTTPException) as exc_info:
        refresh_router.start_refresh(
            refresh_router.RefreshStartRequest(institutions=["not_a_connector"])
        )

    assert exc_info.value.status_code == 422
    assert "not_a_connector" in exc_info.value.detail
