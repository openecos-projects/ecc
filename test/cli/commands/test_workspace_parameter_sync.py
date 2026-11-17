"""Workspace parameter metadata and configuration inspection stay in sync (#364).

Creation registers the entry before its directory exists, so the projection is
derived once creation is committed; parameter writes re-derive it; and
``ecc config --workspace`` presents the workspace's own params.toml values as
the workspace layer beside the project layers.
"""

import json
from pathlib import Path

from chipcompiler.cli import main as cli_main


def _write_project(tmp_path: Path, minimal_ics55_pdk_factory, *, frequency_mhz: float = 100.0):
    project = tmp_path / "gcd"
    (project / "rtl").mkdir(parents=True)
    (project / "rtl" / "gcd.v").write_text("module gcd(input clk); endmodule\n")
    pdk_root = minimal_ics55_pdk_factory(tmp_path / "pdk")
    (project / "ecc.toml").write_text(
        '[design]\nname = "gcd"\ntop = "gcd"\nrtl = ["rtl/gcd.v"]\n'
        f'clock_port = "clk"\nfrequency_mhz = {frequency_mhz}\n\n'
        f'[pdk]\nname = "ics55"\nroot = "{pdk_root}"\n\n'
        '[flow]\npreset = "rtl2gds"\n'
    )
    return project


def _run(*args: str) -> int:
    return cli_main.run([*args, "--plain"])


def _patch(project: Path, workspace_id: str) -> dict:
    document = json.loads((project / "project.json").read_text())
    entry = next(item for item in document["workspaces"] if item["workspace_id"] == workspace_id)
    return entry["parameter_patch"]


def test_parameter_patch_tracks_create_derive_and_apply(
    tmp_path, minimal_ics55_pdk_factory, capsys, plain_records
):
    project = _write_project(tmp_path, minimal_ics55_pdk_factory)
    frequency = {"from": 100.0, "to": 500.0}

    assert (
        _run(
            "workspace",
            "create",
            "parent_500",
            "--from",
            "Synthesis",
            "--to",
            "Synthesis",
            "--set",
            "design.frequency_mhz=500",
            "--project",
            str(project),
        )
        == 0
    )
    assert _patch(project, "parent_500")["frequency_max"] == frequency

    assert (
        _run(
            "workspace",
            "derive",
            "parent_500",
            "child_600",
            "--from",
            "Synthesis",
            "--project",
            str(project),
        )
        == 0
    )
    assert _patch(project, "child_600")["frequency_max"] == frequency

    assert (
        _run(
            "param",
            "apply",
            "--project",
            str(project),
            "--workspace",
            "child_600",
            "--set",
            "design.frequency_mhz=600",
        )
        == 0
    )
    assert _patch(project, "child_600")["frequency_max"] == {"from": 100.0, "to": 600.0}
    assert _patch(project, "parent_500")["frequency_max"] == frequency

    capsys.readouterr()
    assert _run("config", "--project", str(project), "--workspace", "child_600") == 0
    records = plain_records(capsys.readouterr().out)
    assert {
        (record["scope"], record["value"], record["source"])
        for record in records
        if record.get("kind") == "param" and record.get("key") == "design.frequency_mhz"
    } == {
        # The project layers stay visible beside the workspace's own value, and
        # the create-time --set is labelled as provenance, not as the value.
        ("project", "100.0", "ecc.toml"),
        ("workspace", "600.0", "workspace"),
        ("workspace", "500.0", "cli (create-time)"),
    }


def test_workspace_param_set_and_unset_keep_the_patch_in_sync(tmp_path, minimal_ics55_pdk_factory):
    project = _write_project(tmp_path, minimal_ics55_pdk_factory)
    assert (
        _run(
            "workspace",
            "create",
            "baseline",
            "--from",
            "Synthesis",
            "--to",
            "Synthesis",
            "--project",
            str(project),
        )
        == 0
    )
    assert "frequency_max" not in _patch(project, "baseline")

    assert (
        _run(
            "param",
            "set",
            "design.frequency_mhz",
            "700",
            "--project",
            str(project),
            "--workspace",
            "baseline",
        )
        == 0
    )
    assert _patch(project, "baseline")["frequency_max"] == {"from": 100.0, "to": 700.0}

    assert (
        _run(
            "param",
            "unset",
            "design.frequency_mhz",
            "--project",
            str(project),
            "--workspace",
            "baseline",
        )
        == 0
    )
    # Back at the manifest base value: the patch no longer carries the key.
    assert "frequency_max" not in _patch(project, "baseline")
