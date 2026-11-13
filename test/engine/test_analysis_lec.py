from types import SimpleNamespace

from chipcompiler.engine.analysis import collect_workspace_projections
from test.flow_fixture import step_fields

STEP = "lec@Synthesis"
TOOL = "kepler_formal"


def test_analysis_emits_the_lec_result_of_an_inserted_step(tmp_path):
    fields = step_fields(STEP, TOOL)
    output = tmp_path / fields["directory"] / "output"
    output.mkdir(parents=True)
    (output / f"gcd_{STEP}_result.json").write_text("{}")
    workspace = SimpleNamespace(
        directory=tmp_path,
        flow=SimpleNamespace(
            data={
                "schema_version": 2,
                "steps": [{"name": STEP, "tool": TOOL, "state": "Success", **fields}],
            }
        ),
        design=SimpleNamespace(name="gcd"),
    )

    projections = collect_workspace_projections(workspace, "ws-1")

    lec_artifact = next(
        artifact for artifact in projections["artifacts"] if artifact["kind"] == "lec_result"
    )
    assert lec_artifact["reference"] == f"{fields['directory']}/output/gcd_{STEP}_result.json"
    assert lec_artifact["availability"] == "available"
