import json
import os
import re

import pytest


def create_cli_project(tmp_path, name="gcd", pdk_root=None, freq=100.0):
    project_dir = tmp_path / name
    project_dir.mkdir(exist_ok=True)
    (project_dir / "rtl").mkdir(exist_ok=True)
    (project_dir / "constraints").mkdir(exist_ok=True)
    (project_dir / "runs").mkdir(exist_ok=True)

    rtl_file = project_dir / "rtl" / "gcd.v"
    rtl_file.write_text("module gcd(input clk); endmodule\n")

    if pdk_root is None:
        pdk_root = tmp_path / "ics55"
        pdk_root.mkdir(exist_ok=True)

    toml = f'''[design]
name = "{name}"
top = "{name}"
rtl = ["rtl/gcd.v"]
clock_port = "clk"
frequency_mhz = {freq}

[pdk]
name = "ics55"
root = "{pdk_root}"

[flow]
preset = "rtl2gds"
run = "default"
'''
    (project_dir / "ecc.toml").write_text(toml)
    return str(project_dir)


FLOW_JSON_DEFAULTS = {
    "main": [
        {"name": "Synthesis", "tool": "yosys", "state": "Success", "runtime": "0:00:18"},
        {"name": "Floorplan", "tool": "ecc", "state": "Success", "runtime": "0:00:04"},
    ],
    "inspect": [
        {"name": "Synthesis", "tool": "yosys", "state": "Success", "runtime": "0:00:05"},
        {"name": "Floorplan", "tool": "ecc", "state": "Success", "runtime": "0:00:03"},
        {"name": "CTS", "tool": "ecc", "state": "Success", "runtime": "0:00:04"},
    ],
    "pretty": [
        {"name": "Synthesis", "tool": "yosys", "state": "Success", "runtime": "0:00:05"},
    ],
}


def create_flow_json(run_dir, steps=None, profile="inspect"):
    home = os.path.join(run_dir, "home")
    os.makedirs(home, exist_ok=True)
    if steps is None:
        steps = FLOW_JSON_DEFAULTS[profile]
    with open(os.path.join(home, "flow.json"), "w") as f:
        json.dump({"steps": steps}, f)


def create_step_dir(run_dir, step_name, tool, subdirs=None, files=None):
    step_dir = os.path.join(run_dir, f"{step_name}_{tool}")
    os.makedirs(step_dir, exist_ok=True)
    if subdirs:
        for subdir in subdirs:
            os.makedirs(os.path.join(step_dir, subdir), exist_ok=True)
    if files:
        for relpath, content in files.items():
            file_path = os.path.join(step_dir, relpath)
            os.makedirs(os.path.dirname(file_path), exist_ok=True)
            with open(file_path, "w") as f:
                f.write(content)
    return step_dir


def create_workspace_config(run_dir, files):
    config_dir = os.path.join(run_dir, "config")
    os.makedirs(config_dir, exist_ok=True)
    for name, content in files.items():
        with open(os.path.join(config_dir, name), "w") as f:
            f.write(content)


def create_cts_workspace_config(run_dir):
    create_workspace_config(
        run_dir,
        {
            "flow_config.json": "{}",
            "db_default_config.json": "{}",
            "cts_default_config.json": "{}",
        },
    )


def create_dreamplace_workspace_config(run_dir):
    create_workspace_config(run_dir, {"dreamplace.json": "{}"})


def create_ecc_workspace_config(run_dir, step_config):
    create_workspace_config(
        run_dir,
        {
            "flow_config.json": "{}",
            "db_default_config.json": "{}",
            step_config: "{}",
        },
    )


def has_disclosure(line):
    return bool(
        re.search(r"ecc (?:check|run|status|log|metrics|artifacts|config|diagnose|param)\b", line)
        or '"ecc ' in line
        or "=ecc " in line
    )


def mock_pdk_validation(monkeypatch):
    monkeypatch.setattr(
        "chipcompiler.cli.project.config._validate_pdk_contents",
        lambda name, root: None,
    )


@pytest.fixture(name="create_cli_project")
def create_cli_project_fixture(tmp_path):
    def factory(name="gcd", pdk_root=None, freq=100.0):
        return create_cli_project(tmp_path, name=name, pdk_root=pdk_root, freq=freq)

    return factory


@pytest.fixture(name="create_flow_json")
def create_flow_json_fixture():
    return create_flow_json


@pytest.fixture(name="create_step_dir")
def create_step_dir_fixture():
    return create_step_dir


@pytest.fixture(name="create_workspace_config")
def create_workspace_config_fixture():
    return create_workspace_config


@pytest.fixture(name="create_cts_workspace_config")
def create_cts_workspace_config_fixture():
    return create_cts_workspace_config


@pytest.fixture(name="create_dreamplace_workspace_config")
def create_dreamplace_workspace_config_fixture():
    return create_dreamplace_workspace_config


@pytest.fixture(name="create_ecc_workspace_config")
def create_ecc_workspace_config_fixture():
    return create_ecc_workspace_config


@pytest.fixture(name="has_disclosure")
def has_disclosure_fixture():
    return has_disclosure


@pytest.fixture(name="mock_pdk_validation")
def mock_pdk_validation_fixture(monkeypatch):
    def factory():
        mock_pdk_validation(monkeypatch)

    return factory
