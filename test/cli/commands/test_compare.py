import json
import shlex
from types import SimpleNamespace

import pytest

from chipcompiler.cli import main as cli_main
from chipcompiler.engine.snapshot import create_engineering_snapshot


@pytest.fixture
def saved_snapshots(tmp_path):
    root = tmp_path / "source"
    (root / "home").mkdir(parents=True)
    workspace = SimpleNamespace(
        directory=root,
        flow=SimpleNamespace(data={"steps": [{"name": "sta", "tool": "ecc", "state": "Success"}]}),
        home=SimpleNamespace(data={}),
        parameters=SimpleNamespace(data={"design": "gcd", "frequency_mhz": 100}),
        design=SimpleNamespace(name="gcd"),
    )
    snapshot = create_engineering_snapshot(workspace, workspace_id="compare-gcd")
    snapshot["metrics"] = [
        {
            "id": "sta_setup_wns",
            "value": -0.12,
            "scope": "workspace",
            "corner": "slow",
            "analysis_group": "sta",
            "direction": "higher_is_better",
        }
    ]
    before = tmp_path / "before.json"
    after = tmp_path / "after.json"
    before.write_text(json.dumps(snapshot), encoding="utf-8")
    snapshot["workspaceRevision"] = 2
    snapshot["metrics"][0]["value"] = -0.08
    after.write_text(json.dumps(snapshot), encoding="utf-8")
    return before, after


def _arguments(paths, *options):
    before, after = paths
    return ["compare", "run", "--baseline", str(before), "--current", str(after), *options]


def test_compare_json_is_read_only_and_does_not_load_workspace(
    saved_snapshots, tmp_path, monkeypatch, capsys
):
    monkeypatch.chdir(tmp_path)
    files_before = {path: path.read_bytes() for path in tmp_path.rglob("*") if path.is_file()}

    def unexpected(*args, **kwargs):
        pytest.fail("offline compare must not load a workspace or generate a snapshot")

    monkeypatch.setattr("chipcompiler.data.load_workspace", unexpected)
    monkeypatch.setattr("chipcompiler.engine.snapshot.create_engineering_snapshot", unexpected)

    assert cli_main.run(_arguments(saved_snapshots, "--json")) == 0

    records = json.loads(capsys.readouterr().out)
    assert len(records) == 1
    record = records[0]
    assert record["record"] == "run_comparison"
    assert record["status"] == "success"
    assert record["baseline"]["workspace_revision"] == 1
    assert record["current"]["workspace_revision"] == 2
    assert record["metrics"][0]["delta"] == pytest.approx(0.04)
    assert record["summary"]["overall"] == "improved"
    assert all(item["content_comparison"] == "unknown" for item in record["artifacts"])
    assert {
        path: path.read_bytes() for path in tmp_path.rglob("*") if path.is_file()
    } == files_before


@pytest.mark.parametrize("options", [[], ["--plain"]])
def test_compare_text_and_plain(saved_snapshots, options, capsys):
    assert cli_main.run(_arguments(saved_snapshots, *options)) == 0

    captured = capsys.readouterr()
    assert captured.err == ""
    assert "run_comparison" in captured.out
    assert "improved" in captured.out
    if options:
        fields = dict(field.split("=", 1) for field in shlex.split(captured.out))
        assert fields["status"] == "success"


def test_same_file_comparison_is_valid(saved_snapshots, capsys):
    before, _after = saved_snapshots

    assert cli_main.run(_arguments((before, before), "--json")) == 0
    assert json.loads(capsys.readouterr().out)[0]["summary"]["overall"] == "unchanged"


def test_regression_does_not_fail_command(saved_snapshots, capsys):
    assert cli_main.run(_arguments(tuple(reversed(saved_snapshots)), "--json")) == 0
    assert json.loads(capsys.readouterr().out)[0]["summary"]["overall"] == "regressed"


@pytest.mark.parametrize("role", ["baseline", "current"])
@pytest.mark.parametrize("payload", [None, "{", "[]", '{"schemaVersion":999}', "\xff"])
def test_bad_input_has_structured_error(saved_snapshots, role, payload, capsys):
    before, after = saved_snapshots
    path = before if role == "baseline" else after
    if payload is None:
        path.unlink()
    elif payload == "\xff":
        path.write_bytes(b"\xff")
    else:
        path.write_text(payload, encoding="utf-8")

    assert cli_main.run(_arguments(saved_snapshots, "--json")) == 1

    error = json.loads(capsys.readouterr().out)[0]
    assert error["error"] == "snapshot_read_failed"
    assert error["role"] == role


def test_duplicate_metrics_have_structured_error(saved_snapshots, capsys):
    before, _after = saved_snapshots
    snapshot = json.loads(before.read_text())
    snapshot["metrics"].append(snapshot["metrics"][0])
    before.write_text(json.dumps(snapshot))

    assert cli_main.run(_arguments(saved_snapshots, "--json")) == 1

    error = json.loads(capsys.readouterr().out)[0]
    assert error["error"] == "snapshot_compare_failed"
    assert "duplicate" in error["reason"]


def test_compare_rejects_conflicting_output_modes(saved_snapshots, capsys):
    assert cli_main.run(_arguments(saved_snapshots, "--json", "--plain")) == 2
    assert "cannot be used together" in capsys.readouterr().err


def test_compare_requires_both_paths(capsys):
    assert cli_main.run(["compare", "run", "--baseline", "before.json"]) == 2
    assert "--current" in capsys.readouterr().err


@pytest.mark.parametrize(
    "command", [["--help"], ["compare", "--help"], ["compare", "run", "--help"]]
)
def test_compare_help(command, capsys):
    assert cli_main.run(command) == 0
    output = capsys.readouterr().out
    assert "compare" in output.lower()


def test_bad_input_plain_error_uses_existing_contract(tmp_path, capsys):
    missing = tmp_path / "missing.json"

    assert cli_main.run(_arguments((missing, missing), "--plain")) == 1

    captured = capsys.readouterr()
    assert "snapshot_read_failed" in captured.err + captured.out
