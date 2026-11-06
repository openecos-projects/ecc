"""Each step's run results live in its step directory; flow.json indexes them."""

import json

from chipcompiler.data import StateEnum, Workspace
from chipcompiler.data.step.results import STATE_FILE
from chipcompiler.data.workspace import Flow
from chipcompiler.data.workspace.flow_ledger import save_ledger, set_flow_state
from chipcompiler.data.workspace.flow_types import load_flow_document
from chipcompiler.engine.flow import EngineFlow
from test.flow_fixture import step_fields


def _flow(tmp_path, *steps: tuple[str, str]) -> EngineFlow:
    """A saved ledger whose step directories exist, with the given states."""
    workspace = Workspace(directory=tmp_path, flow=Flow(path=tmp_path / "home" / "flow.json"))
    (tmp_path / "home").mkdir()
    flow = EngineFlow(workspace)
    flow.workspace.flow.data = {
        "schema_version": 2,
        "steps": [
            flow.init_flow_step(name, "ecc", state, index=index)
            for index, (name, state) in enumerate(steps, start=1)
        ],
    }
    for record in flow.workspace.flow.steps():
        (tmp_path / str(record.get("directory"))).mkdir()
    assert flow.save()
    return flow


def _state_file(tmp_path, directory: str) -> dict:
    return json.loads((tmp_path / directory / STATE_FILE).read_text(encoding="utf-8"))


def test_saving_the_ledger_writes_each_step_results_into_its_directory(tmp_path):
    flow = _flow(tmp_path, ("route", "Success"), ("filler", "Unstart"))
    route = flow.get_step("route", "ecc")
    assert route is not None
    route["runtime"] = "0:1:5"
    route["info"] = {"execution": {"started_at": 1.0}, "golden_verilog": "kept.v"}

    assert flow.save()

    assert _state_file(tmp_path, "01_route_ecc") == {
        "schema_version": 1,
        "step": "route",
        "tool": "ecc",
        "state": "Success",
        "runtime": "0:1:5",
        "peak memory (mb)": 0,
        "run_markers": {"execution": {"started_at": 1.0}},
    }
    assert _state_file(tmp_path, "02_filler_ecc")["state"] == "Unstart"


def test_steps_without_a_directory_keep_their_results_in_the_ledger_only(tmp_path):
    flow = _flow(tmp_path, ("route", "Success"))
    flow.add_step("filler", "ecc", StateEnum.Unstart)

    assert not (tmp_path / "02_filler_ecc").exists()
    assert load_flow_document(flow.workspace.flow.path).get("steps", [])[1]["state"] == "Unstart"


def test_an_interrupted_save_resolves_to_the_step_directories(tmp_path):
    flow = _flow(tmp_path, ("route", "Ongoing"))
    ledger = (tmp_path / "home" / "flow.json").read_text(encoding="utf-8")
    assert set_flow_state(flow.workspace.flow, "route", "ecc", StateEnum.Success, runtime="0:0:9")
    # The save wrote state.json; flow.json is put back as if the process died
    # before writing it.
    (tmp_path / "home" / "flow.json").write_text(ledger, encoding="utf-8")

    (route,) = load_flow_document(flow.workspace.flow.path).get("steps", [])

    assert (route["state"], route.get("runtime")) == ("Success", "0:0:9")


def test_a_ledger_edited_by_another_writer_keeps_its_results(tmp_path):
    flow = _flow(tmp_path, ("route", "Success"))
    path = tmp_path / "home" / "flow.json"
    document = json.loads(path.read_text(encoding="utf-8"))
    document["steps"][0]["state"] = "Unstart"  # e.g. ECOS resetting a staged rerun
    path.write_text(json.dumps(document), encoding="utf-8")

    reloaded = EngineFlow(flow.workspace)

    assert reloaded.workspace.flow.steps()[0]["state"] == "Unstart"
    assert reloaded.save()
    assert _state_file(tmp_path, "01_route_ecc")["state"] == "Unstart"


def test_a_failed_ledger_write_restores_the_step_results(tmp_path, monkeypatch):
    flow = _flow(tmp_path, ("route", "Ongoing"))
    before = (tmp_path / "01_route_ecc" / STATE_FILE).read_text(encoding="utf-8")
    monkeypatch.setattr("chipcompiler.utility.json_write", lambda *_args, **_kwargs: False)

    assert not set_flow_state(flow.workspace.flow, "route", "ecc", StateEnum.Success)

    assert (tmp_path / "01_route_ecc" / STATE_FILE).read_text(encoding="utf-8") == before
    assert flow.workspace.flow.steps()[0]["state"] == "Ongoing"


def test_ledgers_outside_a_workspace_home_write_no_step_results(tmp_path):
    path = tmp_path / "notes" / "flow.json"
    path.parent.mkdir()
    (tmp_path / "route_ecc").mkdir()
    flow = Flow(
        path=path,
        data={
            "schema_version": 2,
            "steps": [
                {
                    "name": "route",
                    "tool": "ecc",
                    "state": "Unstart",
                    **step_fields("route", "ecc"),
                }
            ],
        },
    )

    assert save_ledger(flow)

    assert not (tmp_path / "route_ecc" / STATE_FILE).exists()
    assert "step_results_digest" not in json.loads(path.read_text(encoding="utf-8"))
