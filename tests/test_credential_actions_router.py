from __future__ import annotations

import pytest
from fastapi import HTTPException

from backend.routers import credential_actions
from backend.routers.credential_actions import (
    CredentialStoreLaunch,
    credential_store_status,
    launch_credential_store,
)


def test_launch_credential_store_starts_broker_without_credentials(monkeypatch):
    launched: dict = {}

    class DummyProcess:
        pid = 4242

    def fake_popen(cmd, **kwargs):
        launched["cmd"] = cmd
        launched["kwargs"] = kwargs
        return DummyProcess()

    monkeypatch.setattr(credential_actions.subprocess, "Popen", fake_popen)

    response = launch_credential_store(CredentialStoreLaunch(institution="MyPay"))

    assert response["status"] == "launched"
    assert response["institution"] == "mypay"
    assert response["pid"] == 4242
    assert "launched_at" in response
    assert launched["cmd"][1].endswith("credential_broker.py")
    assert launched["cmd"][-2:] == ["--store", "mypay"]
    assert "input" not in launched["kwargs"]
    assert "stdin" not in launched["kwargs"]


def test_launch_credential_store_rejects_invalid_institution():
    with pytest.raises(HTTPException) as exc:
        launch_credential_store(CredentialStoreLaunch(institution="../mypay"))

    assert exc.value.status_code == 422


def test_launch_credential_store_returns_launch_error(monkeypatch):
    def fake_popen(_cmd, **_kwargs):
        raise OSError("no console")

    monkeypatch.setattr(credential_actions.subprocess, "Popen", fake_popen)

    with pytest.raises(HTTPException) as exc:
        launch_credential_store(CredentialStoreLaunch(institution="mypay"))

    assert exc.value.status_code == 500
    assert "Credential broker launch failed" in exc.value.detail


def test_credential_store_status_returns_non_secret_metadata(monkeypatch):
    def fake_metadata(institution):
        assert institution == "mypay"
        return {
            "institution": "mypay",
            "target": "SentryFinance:mypay",
            "exists": True,
            "schema": "v2",
            "kind": "password",
            "stored_at": "2026-05-09T20:30:00+00:00",
            "username": "should-not-leak",
            "password": "should-not-leak",
        }

    monkeypatch.setattr(credential_actions, "get_credential_metadata", fake_metadata)

    response = credential_store_status("MyPay")

    assert response == {
        "institution": "mypay",
        "exists": True,
        "schema": "v2",
        "kind": "password",
        "stored_at": "2026-05-09T20:30:00+00:00",
    }
