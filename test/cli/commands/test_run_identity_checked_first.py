"""A malformed run identity is rejected before the project is touched (#431).

`--run-id`, `--runtime-id` and `--log-file` are validated where the run
process is registered. A fresh run gets there only after its workspace has
been created and declared, so a rejected command used to leave that
workspace behind, and `--overwrite` had already replaced the old one.
"""

import json
import os
import uuid
from types import SimpleNamespace

import pytest

from chipcompiler.cli import main as cli_main
from chipcompiler.engine import EngineFlow


class LedgerOnlyFlow(EngineFlow):
    """The real flow ledger, without step workspaces or tool execution."""

    def create_step_workspaces(self, **_kwargs):
        self.workspace_steps = list(self.workspace.flow.data.get("steps", []))

    def run_steps(self, **_kwargs):
        return True


@pytest.fixture
def fresh_project(tmp_path, monkeypatch, minimal_ics55_pdk_factory):
    """A project whose fresh runs build a real workspace without running tools."""
    monkeypatch.setattr("chipcompiler.engine.EngineFlow", LedgerOnlyFlow)
    monkeypatch.setattr(
        "chipcompiler.rtl2gds.builder.build_rtl2gds_flow",
        lambda *, skip=(), lec_engine=None: [("synthesis", "yosys", "Unstart")],
    )
    monkeypatch.setattr(
        "chipcompiler.cli.project.config._validate_pdk_contents",
        lambda name, root, overrides=None: None,
    )
    project = tmp_path / "project"
    assert cli_main.run(["init", str(project), "--design-name", "gcd"]) == 0
    pdk = minimal_ics55_pdk_factory(tmp_path / "pdk")
    (project / "gcd.v").write_text("module gcd(input clk); endmodule\n")
    assert cli_main.run(["project", "set", "design.rtl", "gcd.v", "--project", str(project)]) == 0
    config = project / "ecc.toml"
    config.write_text(config.read_text().replace('root = ""', f'root = "{pdk}"'))
    return project


def _entries(project):
    return sorted(str(path.relative_to(project)) for path in project.rglob("*"))


def _declared(project):
    manifest = project / "project.json"
    if not manifest.exists():
        return []
    return [entry["workspace_id"] for entry in json.loads(manifest.read_text())["workspaces"]]


RUN_ID = str(uuid.uuid4())

REJECTED = [
    pytest.param(["--run-id", "not-a-uuid"], "invalid_run_id", id="run-id-not-a-uuid"),
    pytest.param(["--run-id", RUN_ID.upper()], "invalid_run_id", id="run-id-not-canonical"),
    pytest.param(["--runtime-id", "two words"], "invalid_runtime_id", id="runtime-id"),
    pytest.param(
        ["--run-id", RUN_ID, "--log-file", "log/other.log"], "invalid_log_path", id="log-file"
    ),
]


@pytest.mark.parametrize(("options", "code"), REJECTED)
def test_rejected_run_identity_creates_nothing(fresh_project, capsys, options, code):
    before = _entries(fresh_project)

    exit_code = cli_main.run(
        ["run", "--workspace", "w1", *options, "--project", str(fresh_project), "--plain"]
    )

    assert exit_code == 1
    assert f"error={code}" in capsys.readouterr().out
    assert _entries(fresh_project) == before
    assert _declared(fresh_project) == []


def test_fresh_run_still_accepts_set_after_a_rejected_run_id(fresh_project, capsys):
    target = ["--workspace", "w1", "--set", "placement:place.target_density=0.55"]
    project = ["--project", str(fresh_project), "--plain"]

    assert cli_main.run(["run", *target, "--run-id", "not-a-uuid", *project]) == 1
    capsys.readouterr()
    assert cli_main.run(["run", *target, "--run-id", RUN_ID, *project]) == 0

    assert "set_requires_fresh_run" not in capsys.readouterr().out
    assert _declared(fresh_project) == ["w1"]


def test_rejected_run_identity_does_not_overwrite(fresh_project, capsys):
    project = ["--project", str(fresh_project), "--plain"]
    assert cli_main.run(["run", "--workspace", "w1", *project]) == 0
    marker = fresh_project / "w1" / "home" / "kept.txt"
    marker.write_text("from the first run\n")
    capsys.readouterr()

    exit_code = cli_main.run(
        ["run", "--workspace", "w1", "--overwrite", "--run-id", "not-a-uuid", *project]
    )

    assert exit_code == 1
    assert "error=invalid_run_id" in capsys.readouterr().out
    assert marker.read_text() == "from the first run\n"
    assert not list(fresh_project.glob("w1.overwritten-*"))


@pytest.mark.parametrize(
    ("replay_options", "result_survived"),
    [
        pytest.param([], True, id="default-log"),
        pytest.param(["--log-file", f"log/{RUN_ID}.log"], True, id="explicit-log"),
        pytest.param(["--only", "synthesis", "--force"], True, id="single-step"),
        pytest.param(["--overwrite"], True, id="overwrite"),
        pytest.param(["--log-file", f"log/{RUN_ID}.log"], False, id="log-without-result"),
    ],
)
def test_repeated_run_id_preserves_the_original_log_and_result(
    fresh_project, capsys, replay_options, result_survived
):
    log = f"log/{RUN_ID}.log"
    args = [
        "run",
        "--project",
        str(fresh_project),
        "--workspace",
        "w1",
        "--run-id",
        RUN_ID,
        "--plain",
    ]
    assert cli_main.run(args) == 0
    capsys.readouterr()
    workspace = fresh_project / "w1"
    result = workspace / "log" / f"{RUN_ID}.run.json"
    if not result_survived:
        result.unlink()
    files = (
        workspace / log,
        result,
        workspace / "home" / "flow.json",
    )
    original = tuple(path.read_bytes() if path.exists() else None for path in files)

    exit_code = cli_main.run([*args, *replay_options])

    assert tuple(path.read_bytes() if path.exists() else None for path in files) == original
    assert exit_code == 1
    assert "error=run_id_already_used" in capsys.readouterr().out


def test_run_accepts_an_empty_log_preopened_by_the_launcher(tmp_path):
    from chipcompiler.cli.project.run_process import locked_run_session

    log_path = f"log/{RUN_ID}.log"
    log = tmp_path / log_path
    log.parent.mkdir()
    log.touch()
    request = SimpleNamespace(run_id=RUN_ID, log_file=log_path, no_wait=True)

    with locked_run_session(request, tmp_path) as fd:
        assert fd is not None
        os.write(fd, b"run output\n")

    assert log.read_bytes() == b"run output\n"
