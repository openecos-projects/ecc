from types import SimpleNamespace

import pytest

from chipcompiler.engine.analysis import collect_workspace_projections
from test.flow_fixture import step_fields


def _lec_workspace(tmp_path, tool, result_name):
    design = "gcd"
    step_dir = tmp_path / result_name
    output = step_dir / "output"
    output.mkdir(parents=True)
    (output / f"{design}_lec_result.json").write_text("{}")

    workspace = SimpleNamespace(
        directory=tmp_path,
        flow=SimpleNamespace(
            data={
                "schema_version": 2,
                "steps": [
                    {
                        "name": "lec",
                        "tool": tool,
                        "state": "Success",
                        **step_fields("lec", tool),
                    }
                ],
            }
        ),
        design=SimpleNamespace(name=design),
    )
    return workspace


@pytest.mark.parametrize(
    ("tool", "directory"),
    [
        ("kepler_formal", "lec_kepler_formal"),
        ("yosys_lec", "lec_yosys_lec"),
        ("lec_dual", "lec_dual"),
    ],
)
def test_analysis_emits_lec_result_for_ledger_tool(tmp_path, tool, directory):
    workspace = _lec_workspace(tmp_path, tool, directory)

    projections = collect_workspace_projections(workspace, "ws-1")

    lec_artifact = next(
        artifact for artifact in projections["artifacts"] if artifact["kind"] == "lec_result"
    )
    assert lec_artifact["reference"] == f"{directory}/output/gcd_lec_result.json"
    assert lec_artifact["availability"] == "available"
