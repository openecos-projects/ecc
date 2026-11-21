import logging
import os

import pytest

from chipcompiler.utility.threads import ENV_THREADS, resolve_thread_count, thread_budget


def test_budget_defaults_to_the_affinity_set(monkeypatch):
    monkeypatch.delenv(ENV_THREADS, raising=False)
    monkeypatch.setattr(os, "sched_getaffinity", lambda _pid: {0, 1, 2})
    assert thread_budget() == 3


def test_env_threads_overrides_affinity(monkeypatch):
    monkeypatch.setattr(os, "sched_getaffinity", lambda _pid: {0, 1, 2})
    monkeypatch.setenv(ENV_THREADS, "5")
    assert thread_budget() == 5


@pytest.mark.parametrize("value", ["", "0", "-2", "abc", "1.5", "²", "①"])
def test_invalid_env_threads_falls_back_to_affinity(monkeypatch, caplog, value):
    monkeypatch.setattr(os, "sched_getaffinity", lambda _pid: {0, 1})
    monkeypatch.setenv(ENV_THREADS, value)
    with caplog.at_level(logging.WARNING):
        assert thread_budget() == 2
    if value:
        assert "Ignoring invalid" in caplog.text


def test_budget_falls_back_to_cpu_count_on_affinity_os_error(monkeypatch):
    monkeypatch.delenv(ENV_THREADS, raising=False)

    def blocked(_pid):
        raise PermissionError("blocked")

    monkeypatch.setattr(os, "sched_getaffinity", blocked)
    monkeypatch.setattr(os, "cpu_count", lambda: 6)
    assert thread_budget() == 6


def test_resolve_thread_count_validates_explicit_values(monkeypatch):
    monkeypatch.setenv(ENV_THREADS, "4")
    assert resolve_thread_count(None) == 4
    assert resolve_thread_count(None, default=2) == 4
    assert resolve_thread_count(3) == 3
    assert resolve_thread_count(3, default=2) == 3
    for bad in (0, -1, True):
        with pytest.raises(ValueError, match="positive integer"):
            resolve_thread_count(bad)


def test_default_caps_affinity_until_env_overrides(monkeypatch):
    monkeypatch.delenv(ENV_THREADS, raising=False)
    monkeypatch.setattr(os, "sched_getaffinity", lambda _pid: set(range(64)))
    assert thread_budget(default=8) == 8
    assert resolve_thread_count(None, default=8) == 8

    monkeypatch.setattr(os, "sched_getaffinity", lambda _pid: {0, 1, 2})
    assert thread_budget(default=8) == 3

    monkeypatch.setattr(os, "sched_getaffinity", lambda _pid: set(range(64)))
    monkeypatch.setenv(ENV_THREADS, "12")
    assert thread_budget(default=8) == 12
    monkeypatch.setenv(ENV_THREADS, "4")
    assert thread_budget(default=8) == 4

    for bad in (0, -1, True):
        with pytest.raises(ValueError, match="positive integer"):
            thread_budget(default=bad)
