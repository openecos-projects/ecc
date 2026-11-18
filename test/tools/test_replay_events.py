import os

import pytest

from chipcompiler.tools.replay_events import suspend_capture


def test_helper_capture_suspension_restores_opt_in_after_nested_failure(monkeypatch):
    monkeypatch.setenv("ECC_REPLAY_CAPTURE_DIR", "/capture/filler")
    with pytest.raises(RuntimeError, match="helper failed"), suspend_capture():
        assert "ECC_REPLAY_CAPTURE_DIR" not in os.environ
        with suspend_capture():
            assert "ECC_REPLAY_CAPTURE_DIR" not in os.environ
        assert "ECC_REPLAY_CAPTURE_DIR" not in os.environ
        raise RuntimeError("helper failed")
    assert os.environ["ECC_REPLAY_CAPTURE_DIR"] == "/capture/filler"
