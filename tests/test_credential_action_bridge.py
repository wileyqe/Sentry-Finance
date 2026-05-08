from __future__ import annotations

import queue
import threading
from unittest.mock import patch

from backend import sse_topics
from backend.credential_action_bridge import request_action, submit_choice
from backend.events import subscribe, unsubscribe


def test_request_action_broadcasts_and_accepts_choice():
    q = subscribe()
    result: dict[str, str] = {}
    try:
        worker = threading.Thread(
            target=lambda: result.update(
                choice=request_action(
                    institution="mypay",
                    action="password_change",
                    title="Rotate myPay password",
                    prompt="Change or defer?",
                    timeout_seconds=5,
                )
            ),
            daemon=True,
        )
        worker.start()

        msg = q.get(timeout=1)
        payload = msg["data"]
        assert msg["type"] == sse_topics.CREDENTIAL_ACTION_REQUIRED
        assert payload["institution"] == "mypay"
        assert payload["action"] == "password_change"

        assert submit_choice(payload["action_id"], "change_now") is True
        worker.join(timeout=2)
    finally:
        unsubscribe(q)

    assert result["choice"] == "change_now"


def test_request_action_defaults_immediately_without_sse_subscribers():
    with patch("backend.credential_action_bridge.broadcast_event") as broadcast:
        choice = request_action(
            institution="mypay",
            action="password_change",
            title="Rotate myPay password",
            prompt="Change or defer?",
            timeout_seconds=5,
        )

    assert choice == "remind_later"
    broadcast.assert_not_called()


def test_request_action_times_out_to_default_with_subscriber():
    q = subscribe()
    try:
        assert request_action(
            institution="mypay",
            action="password_change",
            title="Rotate myPay password",
            prompt="Change or defer?",
            timeout_seconds=0,
        ) == "remind_later"
        msg = q.get(timeout=1)
        assert msg["type"] == sse_topics.CREDENTIAL_ACTION_REQUIRED
    except queue.Empty:
        raise AssertionError("expected credential action SSE")
    finally:
        unsubscribe(q)
