import json
from copy import deepcopy
from hashlib import sha256
from pathlib import Path

import pytest

from chipcompiler.engine import create_workspace_from_spec
from chipcompiler.engine.workspace.derive import derive_workspace
from chipcompiler.engine.workspace.lifecycle import WorkspaceLifecycleError


def test_derive_rewrites_workspace_paths_without_corrupting_frozen_replay(tmp_path):
    from chipcompiler.engine.workspace.derive import _rewrite_staged_paths

    source, target = str(tmp_path / "source"), str(tmp_path / "target")
    staging = tmp_path / "staging"
    home = staging / "home"
    home.mkdir(parents=True)
    config = home / "flow.json"
    config.write_text(json.dumps({"input": source + "/origin/top.v"}))
    recording = staging / "place_dreamplace/output/geometry/replay/attempts/a"
    recording.mkdir(parents=True)
    evidence = recording / "logical.json"
    original = json.dumps({"source": source + "/origin/top.v", "modules": {}}).encode()
    evidence.write_bytes(original)
    digest = sha256(original).hexdigest()
    manifest = recording / "manifest.json"
    manifest.write_text(json.dumps({"files": {"logical.json": {"sha256": digest}}}))
    manifest_bytes = manifest.read_bytes()

    _rewrite_staged_paths(staging, ((source, target),))

    assert json.loads(config.read_text()) == {"input": target + "/origin/top.v"}
    assert evidence.read_bytes() == original
    assert sha256(evidence.read_bytes()).hexdigest() == digest
    assert manifest.read_bytes() == manifest_bytes


def test_derive_rejects_existing_target(tmp_path):
    source = tmp_path / "source"
    (source / "home").mkdir(parents=True)
    (source / "home" / "engineering-snapshot.json").write_text("{}", encoding="utf-8")

    with pytest.raises(WorkspaceLifecycleError) as excinfo:
        derive_workspace(source, tmp_path)

    assert excinfo.value.code == "workspace_exists"


def test_derive_rejects_source_without_engineering_snapshot(tmp_path):
    source = tmp_path / "source"
    (source / "home").mkdir(parents=True)

    with pytest.raises(WorkspaceLifecycleError) as excinfo:
        derive_workspace(source, tmp_path / "target")

    assert excinfo.value.code == "workspace_invalid"


def test_derive_rejects_target_inside_source(tmp_path):
    source = tmp_path / "source"
    (source / "home").mkdir(parents=True)
    (source / "home" / "engineering-snapshot.json").write_text("{}", encoding="utf-8")

    with pytest.raises(WorkspaceLifecycleError) as excinfo:
        derive_workspace(source, source / "nested" / "target")

    assert excinfo.value.code == "workspace_invalid"
    assert not (source / "nested").exists()


def test_derive_no_wait_leaves_no_target_lock_when_source_busy(tmp_path):
    fcntl = pytest.importorskip("fcntl")
    # "child" sorts before "probe", so a sorted acquisition would create the
    # target lock file before discovering the busy source lock.
    source = tmp_path / "probe"
    (source / "home").mkdir(parents=True)
    (source / "home" / "engineering-snapshot.json").write_text("{}", encoding="utf-8")
    target = tmp_path / "child"

    with (tmp_path / "probe.lock").open("a") as held:
        fcntl.flock(held.fileno(), fcntl.LOCK_EX)
        with pytest.raises(BlockingIOError):
            derive_workspace(source, target, blocking=False)

    assert not (tmp_path / "child.lock").exists()
    assert not target.exists()


def test_derive_sweeps_stale_staging_siblings(tmp_path, minimal_ics55_pdk_factory):
    fixture = Path(__file__).parents[1] / "fixtures" / "workspace_spec" / "valid.json"
    payload = json.loads(fixture.read_text(encoding="utf-8"))
    bindings = deepcopy(payload["workspaceBindings"])
    bindings["inputs"] = {
        key: str(fixture.parent / value) for key, value in bindings["inputs"].items()
    }
    bindings["pdk"]["root"] = str(minimal_ics55_pdk_factory(tmp_path / "pdk"))
    source = tmp_path / "source"
    create_workspace_from_spec(source, payload["workspaceSpec"], bindings)
    stale = tmp_path / ".branch.staging-crashed"
    (stale / "home").mkdir(parents=True)
    (stale / "home" / "engineering-snapshot.json").write_text("{}", encoding="utf-8")
    Path(f"{stale}.lock").write_text("", encoding="utf-8")
    target = tmp_path / "branch"

    derived = derive_workspace(source, target)

    assert derived is not None
    assert target.is_dir()
    assert not stale.exists()
    assert not Path(f"{stale}.lock").exists()
