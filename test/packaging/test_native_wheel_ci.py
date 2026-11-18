"""Native wheel selection must wait for the exact submodule's successful CI."""

import importlib.util
from pathlib import Path

import pytest


@pytest.fixture
def resolver(monkeypatch):
    path = Path(__file__).parents[2] / ".github/scripts/download-native-wheel.py"
    spec = importlib.util.spec_from_file_location("native_wheel_ci", path)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    monkeypatch.setattr(module.time, "sleep", lambda _: None)
    return module


def run(status="completed", conclusion: str | None = "success", commit="pinned"):
    return {"id": 42, "head_sha": commit, "status": status, "conclusion": conclusion}


def artifact(*, expired=False, size=100):
    return {"name": "tool-wheel", "expired": expired, "size_in_bytes": size}


def test_waits_for_pinned_running_ci_and_checks_artifact(resolver, monkeypatch):
    responses = iter(
        [
            {"workflow_runs": [run("in_progress", None)]},
            {"workflow_runs": [run()]},
            {"artifacts": [artifact()]},
        ]
    )
    calls = []

    def api(path):
        calls.append(path)
        return next(responses)

    monkeypatch.setattr(resolver, "api", api)
    assert resolver.wait_for_wheel("owner/repo", "pinned", "tool-wheel") == 42
    assert calls == [
        "repos/owner/repo/actions/workflows/ci.yml/runs?head_sha=pinned&per_page=100",
        "repos/owner/repo/actions/workflows/ci.yml/runs?head_sha=pinned&per_page=100",
        "repos/owner/repo/actions/runs/42/artifacts?per_page=100",
    ]


@pytest.mark.parametrize("runs", [[], [run(conclusion="failure")], [run(commit="other")]])
def test_missing_failed_or_different_commit_does_not_fall_back(resolver, monkeypatch, runs):
    monkeypatch.setattr(resolver, "api", lambda _: {"workflow_runs": runs})
    with pytest.raises(RuntimeError, match="build and validate this pinned submodule"):
        resolver.wait_for_wheel("owner/repo", "pinned", "tool-wheel")


@pytest.mark.parametrize("artifacts", [[], [artifact(expired=True)], [artifact(size=0)]])
def test_successful_run_requires_usable_wheel(resolver, monkeypatch, artifacts):
    responses = iter([{"workflow_runs": [run()]}, {"artifacts": artifacts}])
    monkeypatch.setattr(resolver, "api", lambda _: next(responses))
    with pytest.raises(RuntimeError, match="No successful CI with usable"):
        resolver.wait_for_wheel("owner/repo", "pinned", "tool-wheel")


def test_wait_is_bounded(resolver, monkeypatch):
    monkeypatch.setattr(resolver, "api", lambda _: {"workflow_runs": [run("queued", None)]})
    with pytest.raises(TimeoutError, match="Timed out"):
        resolver.wait_for_wheel("owner/repo", "pinned", "tool-wheel", timeout=0)


def test_api_errors_are_not_reported_as_missing_wheels(resolver, monkeypatch):
    def api(_):
        raise resolver.subprocess.CalledProcessError(1, ["gh", "api"])

    monkeypatch.setattr(resolver, "api", api)
    with pytest.raises(resolver.subprocess.CalledProcessError):
        resolver.wait_for_wheel("owner/repo", "pinned", "tool-wheel")
