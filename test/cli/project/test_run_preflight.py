from types import SimpleNamespace

import pytest

from chipcompiler.cli.project import run_preflight as run_preflight_module
from chipcompiler.cli.project.run_preflight import (
    build_run_preflight,
    output_paths,
    pdk_issues_for_config,
    preflight_failure,
)
from chipcompiler.cli.project.run_preflight import (
    config_issues as real_config_issues,
)
from chipcompiler.cli.project.run_preflight import (
    pdk_issues as real_pdk_issues,
)
from chipcompiler.data.workspace.layout import OutputPaths, StepInput


@pytest.fixture(autouse=True)
def _use_real_resource_preflight(monkeypatch, _stub_run_preflight):
    """Exercise resource checks here; the shared CLI fixture isolates them."""
    monkeypatch.setattr(run_preflight_module, "pdk_issues", real_pdk_issues)
    monkeypatch.setattr(run_preflight_module, "config_issues", real_config_issues)


def test_build_run_preflight_reports_missing_inputs(tmp_path):
    existing = tmp_path / "input.v"
    existing.write_text("module top; endmodule\n")
    missing = tmp_path / "missing.def"
    flow = SimpleNamespace(
        workspace_steps=[
            SimpleNamespace(
                name="place",
                tool="ecc",
                input=StepInput(verilog=existing, def_=missing),
                output=OutputPaths(),
            )
        ]
    )

    result = build_run_preflight(flow, ["place"], only="place", force=False)

    assert result["ready"] is False
    assert result["selected_steps"][0]["tool"] == "ecc"
    assert result["missing_inputs"] == [{"step": "place", "input": "def", "path": str(missing)}]


def test_output_paths_serializes_declared_paths(tmp_path):
    output = tmp_path / "out.v"
    flow = SimpleNamespace(
        workspace_steps=[
            SimpleNamespace(
                name="synthesis",
                output=OutputPaths(verilog=output, db=None),
            )
        ]
    )

    assert output_paths(flow, ["synthesis"]) == {"synthesis": [str(output)]}


def test_build_run_preflight_checks_tools_pdk_and_config(tmp_path, monkeypatch):
    from chipcompiler.cli.inspection.env_probe import FAIL, ProbeResult

    workspace = SimpleNamespace(
        directory=tmp_path / "workspace",
        config={},
        pdk=SimpleNamespace(
            root=tmp_path / "pdk",
            mapping_file=None,
            sdc=None,
            validate=lambda: None,
        ),
    )
    flow = SimpleNamespace(
        workspace=workspace,
        workspace_steps=[
            SimpleNamespace(
                name="filler",
                tool="ecc",
                input=StepInput(),
                output=OutputPaths(),
            )
        ],
    )
    monkeypatch.setattr(
        "chipcompiler.cli.inspection.env_probe.probe_environment",
        lambda components: [ProbeResult("ecc-tools", FAIL, remediation="install ECC")],
    )

    result = build_run_preflight(flow, ["filler"], only=None, force=False)

    assert result["ready"] is False
    assert [issue["component"] for issue in result["tool_issues"]] == ["ecc-tools"]
    assert [issue["component"] for issue in result["pdk_issues"]] == ["pdk-layermap"]
    assert {issue["detail"] for issue in result["config_issues"]} == {
        str(tmp_path / "workspace" / "config" / "db_ecc.json"),
        str(tmp_path / "workspace" / "config" / "filler_ecc.json"),
    }
    assert preflight_failure(result) == {
        "error": "env_not_ready",
        "reason": (
            "ecc-tools: install ECC; "
            "pdk-layermap: Set pdk.overrides.mapping_file to the PDK GDS layer map "
            "(for example techfile/icsprout55.layermap).; "
            "config: Restore the workspace configuration file or recreate the workspace.; "
            "config: Restore the workspace configuration file or recreate the workspace."
        ),
    }


def test_build_run_preflight_accepts_present_pdk_and_config_resources(tmp_path, monkeypatch):
    config_dir = tmp_path / "workspace" / "config"
    config_dir.mkdir(parents=True)
    (config_dir / "db_ecc.json").write_text("{}")
    (config_dir / "filler_ecc.json").write_text("{}")
    mapping_file = tmp_path / "pdk" / "icsprout55.layermap"
    mapping_file.parent.mkdir()
    mapping_file.write_text("layermap")

    flow = SimpleNamespace(
        workspace=SimpleNamespace(
            directory=tmp_path / "workspace",
            config={},
            pdk=SimpleNamespace(
                root=tmp_path / "pdk",
                mapping_file=mapping_file,
                sdc=None,
                validate=lambda: None,
            ),
        ),
        workspace_steps=[
            SimpleNamespace(
                name="filler",
                tool="ecc",
                input=StepInput(),
                output=OutputPaths(),
            )
        ],
    )
    monkeypatch.setattr(
        "chipcompiler.cli.inspection.env_probe.probe_environment",
        lambda components: [],
    )

    result = build_run_preflight(flow, ["filler"], only=None, force=False)

    assert result["ready"] is True
    assert result["issues"] == []


def test_fresh_target_pdk_preflight_does_not_require_generated_sdc(tmp_path, monkeypatch):
    pdk = SimpleNamespace(
        root=tmp_path / "pdk",
        mapping_file=tmp_path / "pdk" / "icsprout55.layermap",
        sdc=None,
        validate=lambda: None,
    )
    pdk.mapping_file.parent.mkdir()
    pdk.mapping_file.write_text("layermap")
    monkeypatch.setattr(
        "chipcompiler.cli.project.config.resolve_pdk_root",
        lambda cfg: str(tmp_path / "pdk"),
    )
    monkeypatch.setattr(
        "chipcompiler.cli.project.config.resolve_pdk_overrides",
        lambda cfg: {},
    )
    monkeypatch.setattr("chipcompiler.data.pdk.get_pdk", lambda *args, **kwargs: pdk)

    issues = pdk_issues_for_config(SimpleNamespace(pdk_name="ics55"), ["filler", "sta"])

    assert issues == []


def test_config_preflight_reports_missing_emir_technology_file(tmp_path):
    config_dir = tmp_path / "workspace" / "config"
    config_dir.mkdir(parents=True)
    (config_dir / "db_ecc.json").write_text("{}")
    emir_config = config_dir / "emir_ecc.json"
    emir_config.write_text("{}")
    workspace = SimpleNamespace(
        directory=tmp_path / "workspace",
        config={"emir": emir_config},
    )
    emir_step = SimpleNamespace(name="emir", tool="ecc")

    issues = real_config_issues(workspace, [emir_step])

    assert issues == [
        {
            "component": "config-emir",
            "status": "fail",
            "required": True,
            "detail": str(emir_config),
            "remediation": "Set technology_file_path in config/emir_ecc.json.",
        }
    ]
