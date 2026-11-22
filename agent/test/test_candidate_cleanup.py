from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from types import SimpleNamespace

import pytest

from agent.cli import _cleanup_candidates
from chipcompiler.utility.workspace_lock import workspace_lock

PREFIX = "candidate-0123456789abcdef-"


def test_cleanup_skips_other_episodes_and_keeps_operation_ledgers(tmp_path: Path):
    source = SimpleNamespace(directory=tmp_path, _registered_directory=lambda: tmp_path)
    artifacts = tmp_path / ".agent" / "candidates"
    ledgers = tmp_path / ".agent" / "operations"
    candidate = artifacts / f"{PREFIX}one"
    other = artifacts / "candidate-1123456789abcdef-one"
    candidate.mkdir(parents=True)
    (candidate / "design.gds").write_text("candidate data")
    other.mkdir()
    ledgers.mkdir()
    receipt = ledgers / f"{PREFIX}one.json"
    receipt.write_text('{"state":"succeeded"}')

    assert _cleanup_candidates(source, PREFIX) == 1
    assert _cleanup_candidates(source, PREFIX) == 0
    assert not candidate.exists()
    assert other.is_dir()
    assert receipt.read_text() == '{"state":"succeeded"}'


def test_cleanup_rejects_a_candidate_with_an_active_lock(tmp_path: Path):
    source = SimpleNamespace(directory=tmp_path, _registered_directory=lambda: tmp_path)
    candidate = tmp_path / ".agent" / "candidates" / f"{PREFIX}one"
    operations = tmp_path / ".agent" / "operations"
    candidate.mkdir(parents=True)
    operations.mkdir()
    starting = operations / f"{PREFIX}starting"
    # ECC creates the sibling lock before accepting or materializing a candidate.
    (operations / f"{starting.name}.lock").touch()
    with workspace_lock(starting), ThreadPoolExecutor() as executor:
        cleanup = executor.submit(_cleanup_candidates, source, PREFIX)
        with pytest.raises(BlockingIOError):
            cleanup.result()
    assert candidate.is_dir()
