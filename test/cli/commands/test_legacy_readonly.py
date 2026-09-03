import json
import os
from pathlib import Path

import pytest

from chipcompiler.cli import main as cli_main


def _create_legacy_workspace(project_dir, pdk_root):
    """A runs/default workspace downgraded to the legacy JSON config shape."""
    from chipcompiler.data import create_workspace

    rtl_path = os.path.join(project_dir, "rtl", "gcd.v")
    os.makedirs(os.path.dirname(rtl_path), exist_ok=True)
    with open(rtl_path, "w") as f:
        f.write("module gcd(input clk, output y); assign y = clk; endmodule\n")

    run_dir = os.path.join(project_dir, "runs", "default")
    workspace = create_workspace(
        directory=run_dir,
        origin_def="",
        origin_verilog=rtl_path,
        pdk="ics55",
        parameters={"pdk": "ics55", "design": "gcd", "top_module": "gcd", "clock": "clk"},
        pdk_root=str(pdk_root),
    )
    assert workspace is not None

    # Downgrade: long-key parameters.json replaces the TOML config, and
    # home.json's parameters pointer goes back to the legacy JSON file.
    home = os.path.join(run_dir, "home")
    legacy = {
        "PDK": "ics55",
        "Design": "gcd",
        "Top module": "gcd",
        "Clock": "clk",
        "Frequency max [MHz]": 250,
    }
    os.unlink(os.path.join(home, "params.toml"))
    with open(os.path.join(home, "parameters.json"), "w") as f:
        json.dump(legacy, f)
    home_json_path = os.path.join(home, "home.json")
    with open(home_json_path) as f:
        home_data = json.load(f)
    home_data["parameters"] = os.path.join(home, "parameters.json")
    with open(home_json_path, "w") as f:
        json.dump(home_data, f)
    return run_dir


@pytest.mark.parametrize(
    "command",
    [
        ["status"],
        ["log"],
        ["check"],
        ["config", "--resolved"],
    ],
)
def test_readonly_commands_never_migrate_legacy_workspace(
    command, tmp_path, capsys, create_cli_project, minimal_ics55_pdk_factory, create_flow_json
):
    """status/log/check/config on a legacy workspace rewrite nothing: they
    never call load_workspace, so no params.toml appears, the legacy JSON is
    not deleted, and home.json keeps its legacy pointer byte-identical."""
    pdk_root = minimal_ics55_pdk_factory(tmp_path / "ics55")
    project_dir = create_cli_project(pdk_root=pdk_root)
    run_dir = _create_legacy_workspace(project_dir, pdk_root)
    create_flow_json(run_dir, profile="main")

    home = os.path.join(run_dir, "home")
    watched = [os.path.join(home, name) for name in ("parameters.json", "home.json")]
    snapshots = {path: Path(path).read_bytes() for path in watched}
    params_toml = os.path.join(home, "params.toml")
    assert not os.path.exists(params_toml)

    rc = cli_main.run([*command, "--project", project_dir, "--json"])

    assert rc == 0
    assert {path: Path(path).read_bytes() for path in watched} == snapshots
    assert not os.path.exists(params_toml)


def test_shadowed_workspace_config_warns_without_touching_files(
    tmp_path, capsys, create_cli_project, minimal_ics55_pdk_factory
):
    """params.toml + parameters.json 并存：run/check/status 输出
    workspace_config_shadowed 提示，且两个文件都原样不动。"""
    from chipcompiler.data import create_workspace

    pdk_root = minimal_ics55_pdk_factory(tmp_path / "ics55")
    project_dir = create_cli_project(pdk_root=pdk_root)
    rtl_path = os.path.join(project_dir, "rtl", "gcd.v")
    run_dir = os.path.join(project_dir, "runs", "default")
    workspace = create_workspace(
        directory=run_dir,
        origin_def="",
        origin_verilog=rtl_path,
        pdk="ics55",
        parameters={"pdk": "ics55", "design": "gcd", "top_module": "gcd", "clock": "clk"},
        pdk_root=str(pdk_root),
    )
    assert workspace is not None

    home = os.path.join(run_dir, "home")
    with open(os.path.join(home, "flow.json"), "w") as f:
        json.dump(
            {
                "steps": [
                    {
                        "name": "Synthesis",
                        "tool": "yosys",
                        "state": "Success",
                        "runtime": "",
                        "peak memory (mb)": 0,
                        "info": {},
                    }
                ]
            },
            f,
        )
    params_path = os.path.join(home, "params.toml")
    legacy_path = os.path.join(home, "parameters.json")
    legacy = {"PDK": "ics55", "Design": "gcd", "Top module": "gcd"}
    with open(legacy_path, "w") as f:
        json.dump(legacy, f)
    params_before = Path(params_path).read_bytes()
    legacy_before = Path(legacy_path).read_bytes()

    rc = cli_main.run(["status", "--project", project_dir, "--json"])

    assert rc == 0
    records = json.loads(capsys.readouterr().out)["records"]
    (warning,) = [r for r in records if r.get("warning") == "workspace_config_shadowed"]
    assert "delete" in warning["reason"]
    assert Path(params_path).read_bytes() == params_before
    assert Path(legacy_path).read_bytes() == legacy_before


def test_shadow_warning_probes_the_explicit_workspace_target(tmp_path, capsys):
    """run --workspace 探测的是显式目标，不是项目推导的 run_dir。"""
    ws = tmp_path / "ws"
    home = ws / "home"
    home.mkdir(parents=True)
    (home / "flow.json").write_text(
        json.dumps(
            {
                "steps": [
                    {
                        "name": "Synthesis",
                        "tool": "yosys",
                        "state": "Success",
                        "runtime": "",
                        "peak memory (mb)": 0,
                        "info": {},
                    }
                ]
            }
        )
    )
    (home / "params.toml").write_text('[params]\ndesign = "gcd"\n')
    (home / "parameters.json").write_text('{"Design": "gcd"}')

    # The workspace lacks PDK assets so the run fails validation — the
    # boundary warning is appended on EVERY outcome, including this one.
    rc = cli_main.run(["run", "--workspace", str(ws), "--json"])

    assert rc != 0
    records = json.loads(capsys.readouterr().out)["records"]
    assert any(r.get("warning") == "workspace_config_shadowed" for r in records)


def test_shadow_warning_fires_on_dangling_legacy_symlink(tmp_path, capsys):
    """lexists 语义：悬挂的 parameters.json 链接同样构成并存。"""
    ws = tmp_path / "ws"
    home = ws / "home"
    home.mkdir(parents=True)
    (home / "flow.json").write_text(json.dumps({"steps": []}))
    (home / "params.toml").write_text('[params]\ndesign = "gcd"\n')
    os.symlink(tmp_path / "gone.json", home / "parameters.json")

    cli_main.run(["run", "--workspace", str(ws), "--json"])

    records = json.loads(capsys.readouterr().out)["records"]
    assert any(r.get("warning") == "workspace_config_shadowed" for r in records)
