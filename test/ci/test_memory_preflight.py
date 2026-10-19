import importlib.util
import json
from pathlib import Path

import pytest


@pytest.fixture
def preflight(monkeypatch, tmp_path):
    path = Path(__file__).parents[2] / ".github/scripts/wait-for-memory.py"
    spec = importlib.util.spec_from_file_location("ci_memory_preflight", path)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    proc = tmp_path / "proc"
    (proc / "self").mkdir(parents=True)
    (proc / "meminfo").write_text("MemTotal: 16777216 kB\nMemAvailable: 14680064 kB\n")
    (proc / "self/cgroup").write_text("0::/runner/job\n")
    root = tmp_path / "cgroup"
    (root / "runner/job").mkdir(parents=True)
    monkeypatch.setattr(module, "PROC", proc)
    monkeypatch.setattr(module, "CGROUP_ROOT", root)
    return module


@pytest.mark.parametrize(
    ("limits", "expected_gib"),
    [
        ({}, 14),
        ({"runner/job": ("max", 0)}, 14),
        ({"runner/job": (16, 4)}, 12),
        ({"runner/job": (24, 1)}, 14),
        ({"runner/job": (16, 4), "runner": (10, 3)}, 7),
        ({"runner/job": ("max", 0), "": (8, 3)}, 5),
        ({"runner/job": (4, 5)}, 0),
    ],
)
def test_effective_headroom_obeys_host_and_all_cgroup_limits(preflight, limits, expected_gib):
    for relative, (limit, used) in limits.items():
        directory = preflight.CGROUP_ROOT / relative
        maximum = "max" if limit == "max" else str(limit * preflight.GIB)
        (directory / "memory.max").write_text(maximum)
        (directory / "memory.current").write_text(str(used * preflight.GIB))

    assert preflight.read_memory() == preflight.MemorySnapshot(
        16 * preflight.GIB, 14 * preflight.GIB, expected_gib * preflight.GIB
    )


@pytest.mark.parametrize("membership", ["4:memory:/runner\n", "0::/missing\n", "0::/../job\n"])
def test_unresolved_cgroup_is_a_probe_failure(preflight, membership, capsys):
    (preflight.PROC / "self/cgroup").write_text(membership)

    assert preflight.main(["--minimum-gib", "1"]) == 1
    assert "::error title=CI memory probe failed::" in capsys.readouterr().out


def test_missing_available_memory_is_not_treated_as_ready(preflight, capsys):
    (preflight.PROC / "meminfo").write_text("MemTotal: 16777216 kB\n")

    assert preflight.main(["--minimum-gib", "1"]) == 1
    assert "CI memory probe failed" in capsys.readouterr().out


def test_missing_cgroup_usage_does_not_fall_back_to_host_memory(preflight, capsys):
    (preflight.CGROUP_ROOT / "runner/memory.max").write_text(str(8 * preflight.GIB))

    assert preflight.main(["--minimum-gib", "1"]) == 1
    assert "CI memory probe failed" in capsys.readouterr().out


@pytest.mark.parametrize(
    ("available", "expected", "waits", "timeout_seconds"),
    [
        ([12], 0, [], 15),
        ([14], 0, [], 15),
        ([11, 12], 0, [10], 15),
        ([11, 11, 11], 1, [10, 5], 15),
        pytest.param([11] * 361, 1, [10] * 360, 3600, id="hour-long-timeout"),
        pytest.param([11] * 359 + [12], 0, [10] * 359, 3600, id="ready-before-hour"),
    ],
)
def test_admission_wait_and_timeout(
    preflight, monkeypatch, capsys, available, expected, waits, timeout_seconds
):
    now = [0]
    slept = []
    observations = iter(available)

    def sleep(seconds):
        slept.append(seconds)
        now[0] += seconds

    def read():
        return preflight.MemorySnapshot(
            16 * preflight.GIB, 14 * preflight.GIB, next(observations) * preflight.GIB
        )

    monkeypatch.setattr(preflight, "read_memory", read)
    monkeypatch.setattr(preflight.time, "monotonic", lambda: now[0])
    monkeypatch.setattr(preflight.time, "sleep", sleep)
    result = preflight.main(
        ["--minimum-gib", "12", "--timeout-seconds", str(timeout_seconds), "--poll-seconds", "10"]
    )

    assert (result, slept) == (expected, waits)
    output = capsys.readouterr().out
    probes = [json.loads(line) for line in output.splitlines() if line.startswith("{")]
    assert probes[-1] == {
        "total_bytes": 16 * preflight.GIB,
        "available_bytes": 14 * preflight.GIB,
        "effective_available_bytes": available[-1] * preflight.GIB,
        "required_bytes": 12 * preflight.GIB,
        "waited_seconds": sum(waits),
    }
    if expected:
        assert "::error title=Insufficient CI memory::" in output
        assert "The design flow was not started" in output
    else:
        assert "Memory preflight passed" in output


def test_zero_timeout_does_not_sleep(preflight, monkeypatch):
    def unexpected_sleep(seconds):
        pytest.fail("zero-timeout preflight must not sleep")

    monkeypatch.setattr(preflight.time, "sleep", unexpected_sleep)
    assert preflight.main(["--minimum-gib", "15", "--timeout-seconds", "0"]) == 1


@pytest.mark.parametrize(
    "arguments",
    [
        ["--minimum-gib", "0"],
        ["--minimum-gib", "1", "--timeout-seconds", "-1"],
        ["--minimum-gib", "1", "--poll-seconds", "0"],
    ],
)
def test_invalid_limits_are_rejected(preflight, arguments):
    with pytest.raises(SystemExit) as error:
        preflight.main(arguments)
    assert error.value.code == 2
