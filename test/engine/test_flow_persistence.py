import json

from chipcompiler.data import Workspace
from chipcompiler.engine.flow import EngineFlow
from chipcompiler.engine.snapshot import create_engineering_snapshot
from test.flow_fixture import step_fields


def test_flow_save_keeps_snapshot_and_persisted_ledger_identical(tmp_path):
    workspace = Workspace(directory=tmp_path)
    (tmp_path / "home").mkdir()
    workspace.flow.path = tmp_path / "home" / "flow.json"
    flow = EngineFlow(workspace)
    workspace.flow.data = {
        "schema_version": 2,
        "steps": [
            {
                "name": "Synthesis",
                "tool": "yosys",
                "state": "Unstart",
                **step_fields("Synthesis", "yosys"),
            }
        ],
    }
    original_steps = workspace.flow.data["steps"]

    assert flow.save() is True
    snapshot = create_engineering_snapshot(workspace)

    assert workspace.flow.path is not None
    assert workspace.flow.path is not None
    assert workspace.flow.path is not None
    assert snapshot["flow"] == json.loads(workspace.flow.path.read_text())
    assert workspace.flow.data == snapshot["flow"]
    assert workspace.flow.data["steps"] is original_steps


def test_failed_ledger_write_rolls_back_the_step_state(tmp_path, monkeypatch):
    import chipcompiler.data.workspace.flow_ledger as flow_ledger
    from chipcompiler.data import StateEnum

    workspace = Workspace(directory=tmp_path)
    (tmp_path / "home").mkdir()
    workspace.flow.path = tmp_path / "home" / "flow.json"
    flow = EngineFlow(workspace)
    workspace.flow.data = {
        "schema_version": 2,
        "steps": [
            {
                "name": "Synthesis",
                "tool": "yosys",
                "state": "Unstart",
                **step_fields("Synthesis", "yosys"),
            }
        ],
    }
    assert flow.save() is True

    monkeypatch.setattr(flow_ledger, "save_ledger", lambda _flow: False)

    assert flow.set_state("Synthesis", "yosys", StateEnum.Ongoing) is False
    assert workspace.flow.data["steps"][0]["state"] == "Unstart"


def test_failed_batch_reset_restores_the_ledger(tmp_path, monkeypatch):
    import chipcompiler.data.workspace.flow_ledger as flow_ledger

    workspace = Workspace(directory=tmp_path)
    (tmp_path / "home").mkdir()
    workspace.flow.path = tmp_path / "home" / "flow.json"
    flow = EngineFlow(workspace)
    workspace.flow.data = {
        "schema_version": 2,
        "steps": [
            {
                "name": "Synthesis",
                "tool": "yosys",
                "state": "Success",
                **step_fields("Synthesis", "yosys"),
            },
            {
                "name": "Floorplan",
                "tool": "ecc",
                "state": "Success",
                **step_fields("Floorplan", "ecc"),
            },
        ],
    }
    assert flow.save() is True
    assert workspace.flow.path is not None
    before = json.loads(workspace.flow.path.read_text())

    monkeypatch.setattr(flow_ledger, "save_ledger", lambda _flow: False)

    assert flow.clear_states() is False
    assert workspace.flow.data == before


def test_failed_ledger_write_preserves_the_existing_schema_version(tmp_path, monkeypatch):
    from chipcompiler.data.workspace.flow_ledger import save_ledger

    workspace = Workspace(directory=tmp_path)
    (tmp_path / "home").mkdir()
    workspace.flow.path = tmp_path / "home" / "flow.json"
    workspace.flow.data = {"schema_version": 2, "steps": []}
    monkeypatch.setattr("chipcompiler.utility.json_write", lambda *_args, **_kwargs: False)

    assert not save_ledger(workspace.flow)
    assert workspace.flow.data["schema_version"] == 2


def test_state_transaction_holds_the_ledger_lock(tmp_path):
    import chipcompiler.data.workspace.flow_ledger as flow_ledger
    from chipcompiler.data import StateEnum

    workspace = Workspace(directory=tmp_path)
    (tmp_path / "home").mkdir()
    workspace.flow.path = tmp_path / "home" / "flow.json"
    workspace.flow.data = {
        "schema_version": 2,
        "steps": [
            {
                "name": "Synthesis",
                "tool": "yosys",
                "state": "Unstart",
                **step_fields("Synthesis", "yosys"),
            }
        ],
    }
    observed = []

    def persist():
        lock = flow_ledger._lock_for(workspace.flow.path)
        owned = "_is_owned"
        observed.append(getattr(lock, owned)())
        return True

    assert (
        flow_ledger.set_flow_state(
            workspace.flow, "Synthesis", "yosys", StateEnum.Ongoing, persist=persist
        )
        is True
    )
    assert observed == [True]
