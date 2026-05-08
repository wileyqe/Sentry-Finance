from __future__ import annotations

import pytest
from fastapi import HTTPException

from backend.routers import credential_actions
from backend.routers.credential_actions import (
    CredentialStoreLaunch,
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

    assert response == {"status": "launched", "institution": "mypay", "pid": 4242}
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
