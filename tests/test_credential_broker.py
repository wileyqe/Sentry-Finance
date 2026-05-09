from __future__ import annotations

import builtins

import pytest

from backend import credential_broker


def test_get_keyring_metadata_mode_raises_without_exiting(monkeypatch):
    real_import = builtins.__import__

    def fake_import(name, *args, **kwargs):
        if name == "keyring":
            raise ImportError("missing keyring")
        return real_import(name, *args, **kwargs)

    monkeypatch.setattr(builtins, "__import__", fake_import)

    with pytest.raises(RuntimeError, match="keyring package not installed"):
        credential_broker._get_keyring(exit_on_error=False)
