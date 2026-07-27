from pathlib import Path
from types import SimpleNamespace

import pytest

from chipcompiler.runtime.requests import (
    LayoutEditApplyRequest,
    LayoutEditBeginRequest,
    LayoutEditDiscardRequest,
    LayoutEditSaveRequest,
)
from chipcompiler.runtime.sessions import WorkspaceSessionRegistry
from chipcompiler.runtime.workspace_api import RuntimeApiError, WorkspaceRuntimeApi


class FakeLayoutModule:
    def __init__(self):
        self.initialize_calls = 0
        self.reset_calls = 0
        self.place_calls = []
        self.sync_calls = []
        self.export_calls = []
        self.session_snapshot_calls = []

    def initialize_geometry_session(self):
        self.initialize_calls += 1
        return True

    def reset_geometry_session(self):
        self.reset_calls += 1
        return True

    def place_instance(self, **kwargs):
        self.place_calls.append(kwargs)
        return True

    def sync_instance_geometry(self, inst_name):
        self.sync_calls.append(inst_name)
        return {
            "ok": True,
            "snapshotRequired": False,
            "updatedShapeCount": 1,
            "insertedShapeCount": 0,
            "deletedShapeCount": 0,
            "missingShapeCount": 0,
            "events": [{"shapeId": 11, "op": "update"}],
        }

    def def_save(self, def_path):
        self.export_calls.append("def")
        Path(def_path).write_text("new def", encoding="utf-8")

    def save_data(self, path):
        self.export_calls.append("db")
        db_path = Path(path)
        db_path.mkdir(parents=True)
        (db_path / "metadata.idb").write_text("new db", encoding="utf-8")
        return True

    def gds_save(self, output_path):
        self.export_calls.append("gds")
        Path(output_path).write_text("new gds", encoding="utf-8")

    def geometry_snapshot_save(self, output_dir):
        self.export_calls.append("geometry")
        geometry_dir = Path(output_dir)
        geometry_dir.mkdir(parents=True)
        (geometry_dir / "geometry.manifest").write_text("new geometry", encoding="utf-8")
        return True

    def geometry_session_snapshot_save(self, output_dir):
        self.session_snapshot_calls.append(Path(output_dir))
        geometry_dir = Path(output_dir)
        geometry_dir.mkdir(parents=True)
        (geometry_dir / "geometry.manifest").write_text("session geometry", encoding="utf-8")
        return True


class FakeEngineDb:
    def __init__(self, module):
        self.ecc_module = module
        self.initialized = False
        self.created_for = []
        self.close_calls = 0

    @property
    def engine(self):
        return self.ecc_module

    def has_init(self):
        return self.initialized

    def create_db_engine(self, step):
        self.created_for.append(step)
        self.initialized = True
        return True

    def close(self):
        self.close_calls += 1
        self.initialized = False


class FakeFlow:
    def __init__(self, workspace, step, module):
        self.workspace = workspace
        self.workspace_step = step
        self.engine_db = FakeEngineDb(module)

    def get_workspace_step(self, name):
        return self.workspace_step if name == self.workspace_step.name else None


def _make_layout_workspace(tmp_path, *, with_db=False):
    workspace_dir = tmp_path / "workspace"
    output_dir = workspace_dir / "Floorplan_ecc" / "output"
    output_dir.mkdir(parents=True)
    output_def = output_dir / "gcd_Floorplan.def.gz"
    output_def.write_text("old def", encoding="utf-8")
    output_db = output_dir / "gcd_Floorplan_db"
    if with_db:
        output_db.mkdir()
        (output_db / "metadata.idb").write_text("old db", encoding="utf-8")
    step = SimpleNamespace(
        name="Floorplan",
        input={"def": None, "verilog": None, "db": None},
        output={
            "def": output_def,
            "db": output_db,
            "gds": output_dir / "gcd_Floorplan.gds",
            "geometry": output_dir / "geometry",
            "geometry_manifest": output_dir / "geometry" / "geometry.manifest",
        },
    )
    workspace = SimpleNamespace(directory=workspace_dir)
    return workspace, step


def _open_api(monkeypatch, tmp_path, *, with_db=False):
    workspace, step = _make_layout_workspace(tmp_path, with_db=with_db)
    module = FakeLayoutModule()
    flow_calls = []

    def build_flow(_workspace):
        flow = FakeFlow(_workspace, step, module)
        flow_calls.append(flow)
        return flow

    monkeypatch.setattr("chipcompiler.runtime.workspace_api.build_flow_for_workspace", build_flow)
    registry = WorkspaceSessionRegistry()
    session = registry.open_session(workspace.directory, workspace=workspace)
    api = WorkspaceRuntimeApi(sessions=registry, persistent_db_enabled=True)
    return api, session, step, module, flow_calls


def _begin(api, workspace_id, **kwargs):
    return api.layout_edit_begin(
        LayoutEditBeginRequest(workspace_id=workspace_id, step="Floorplan", **kwargs)
    )


def _apply(api, edit_session_id, *, revision=0, command_id="move-1"):
    return api.layout_edit_apply(
        LayoutEditApplyRequest(
            edit_session_id=edit_session_id,
            command_id=command_id,
            base_revision=revision,
            operation={
                "kind": "place_instance",
                "instName": "u_sram_0",
                "llx": 1200,
                "lly": 3400,
                "orient": "N",
                "cellmaster": "",
                "source": "",
                "placementStatus": "preserve",
                "createIfMissing": False,
            },
        )
    )


def test_layout_edit_begin_loads_output_def_when_output_db_is_absent(monkeypatch, tmp_path):
    api, session, step, module, flow_calls = _open_api(monkeypatch, tmp_path)

    result = _begin(api, session.workspace_id)

    assert result["source"] == "def"
    assert result["dirty"] is False
    assert Path(result["geometryManifestPath"]).is_file()
    assert module.initialize_calls == 1
    loaded_step = flow_calls[0].engine_db.created_for[0]
    assert loaded_step is not step
    assert loaded_step.input["db"] is None
    assert loaded_step.input["def"] == step.output["def"]


def test_layout_edit_begin_prefers_selected_step_output_db(monkeypatch, tmp_path):
    api, session, step, _module, flow_calls = _open_api(monkeypatch, tmp_path, with_db=True)

    result = _begin(api, session.workspace_id)

    assert result["source"] == "db"
    loaded_step = flow_calls[0].engine_db.created_for[0]
    assert loaded_step.input["db"] == step.output["db"]


def test_layout_edit_apply_calls_place_instance_without_persisting_artifacts(monkeypatch, tmp_path):
    api, session, step, module, _flow_calls = _open_api(monkeypatch, tmp_path)
    begin = _begin(api, session.workspace_id)
    original_def = step.output["def"].read_text(encoding="utf-8")

    result = _apply(api, begin["editSessionId"])

    assert result["revision"] == 1
    assert result["dirty"] is True
    assert result["geometryDelta"]["events"] == [{"shapeId": 11, "op": "update"}]
    assert module.place_calls == [
        {
            "inst_name": "u_sram_0",
            "llx": 1200,
            "lly": 3400,
            "orient": "N",
            "cellmaster": "",
            "source": "",
            "placement_status": "preserve",
            "create_if_missing": False,
        }
    ]
    assert module.sync_calls == ["u_sram_0"]
    assert module.export_calls == []
    assert len(module.session_snapshot_calls) == 2
    assert Path(result["geometryManifestPath"]).is_file()
    assert step.output["def"].read_text(encoding="utf-8") == original_def
    assert not step.output["db"].exists()
    assert not step.output["gds"].exists()
    assert not step.output["geometry"].exists()


def test_layout_edit_save_publishes_staged_outputs_only_after_explicit_save(monkeypatch, tmp_path):
    api, session, step, module, _flow_calls = _open_api(monkeypatch, tmp_path)
    begin = _begin(api, session.workspace_id)
    apply = _apply(api, begin["editSessionId"])

    saved = api.layout_edit_save(
        LayoutEditSaveRequest(
            edit_session_id=begin["editSessionId"],
            expected_revision=apply["revision"],
        )
    )

    assert saved["saved"] is True
    assert saved["dirty"] is False
    assert saved["artifacts"] == {
        "defPath": str(step.output["def"]),
        "dbPath": str(step.output["db"]),
        "gdsPath": str(step.output["gds"]),
        "geometryManifestPath": str(step.output["geometry_manifest"]),
    }
    assert module.export_calls == ["def", "db", "gds", "geometry"]
    assert step.output["def"].read_text(encoding="utf-8") == "new def"
    assert (step.output["db"] / "metadata.idb").read_text(encoding="utf-8") == "new db"
    assert step.output["gds"].read_text(encoding="utf-8") == "new gds"
    geometry_manifest = step.output["geometry"] / "geometry.manifest"
    assert geometry_manifest.read_text(encoding="utf-8") == "new geometry"
    assert not list(step.output["def"].parent.glob(".layout-edit-*"))


def test_layout_edit_discard_drops_in_memory_db_without_publishing(monkeypatch, tmp_path):
    api, session, step, module, flow_calls = _open_api(monkeypatch, tmp_path)
    begin = _begin(api, session.workspace_id)
    _apply(api, begin["editSessionId"])
    geometry_root = Path(begin["geometryManifestPath"]).parent.parent

    result = api.layout_edit_discard(LayoutEditDiscardRequest(begin["editSessionId"]))

    assert result == {
        "editSessionId": begin["editSessionId"],
        "discarded": True,
        "dirty": True,
    }
    assert flow_calls[0].engine_db.close_calls == 1
    assert module.reset_calls == 1
    assert not geometry_root.exists()
    assert step.output["def"].read_text(encoding="utf-8") == "old def"
    assert module.export_calls == []
    with pytest.raises(RuntimeApiError, match="layout edit session not found"):
        _apply(api, begin["editSessionId"])


def test_layout_edit_save_rejects_external_source_change(monkeypatch, tmp_path):
    api, session, step, module, _flow_calls = _open_api(monkeypatch, tmp_path)
    begin = _begin(api, session.workspace_id)
    apply = _apply(api, begin["editSessionId"])
    step.output["def"].write_text("external change", encoding="utf-8")

    with pytest.raises(RuntimeApiError) as exc_info:
        api.layout_edit_save(
            LayoutEditSaveRequest(
                edit_session_id=begin["editSessionId"],
                expected_revision=apply["revision"],
            )
        )

    assert exc_info.value.code == "source_changed"
    assert module.export_calls == []
    assert step.output["def"].read_text(encoding="utf-8") == "external change"


def test_layout_edit_save_rolls_back_when_publish_fails(monkeypatch, tmp_path):
    api, session, step, _module, _flow_calls = _open_api(monkeypatch, tmp_path, with_db=True)
    step.output["gds"].write_text("old gds", encoding="utf-8")
    step.output["geometry"].mkdir()
    (step.output["geometry"] / "geometry.manifest").write_text(
        "old geometry",
        encoding="utf-8",
    )
    begin = _begin(api, session.workspace_id)
    apply = _apply(api, begin["editSessionId"])
    real_replace = __import__("os").replace

    def fail_gds_publish(source, destination):
        if Path(source).name == step.output["gds"].name and Path(destination) == step.output["gds"]:
            raise OSError("simulated publish failure")
        real_replace(source, destination)

    monkeypatch.setattr("chipcompiler.runtime.workspace_api.os.replace", fail_gds_publish)

    with pytest.raises(RuntimeApiError, match="simulated publish failure"):
        api.layout_edit_save(
            LayoutEditSaveRequest(
                edit_session_id=begin["editSessionId"],
                expected_revision=apply["revision"],
            )
        )

    assert step.output["def"].read_text(encoding="utf-8") == "old def"
    assert (step.output["db"] / "metadata.idb").read_text(encoding="utf-8") == "old db"
    assert step.output["gds"].read_text(encoding="utf-8") == "old gds"
    geometry_manifest = step.output["geometry"] / "geometry.manifest"
    assert geometry_manifest.read_text(encoding="utf-8") == "old geometry"


def test_layout_edit_apply_rejects_stale_revision_before_mutation(monkeypatch, tmp_path):
    api, session, _step, module, _flow_calls = _open_api(monkeypatch, tmp_path)
    begin = _begin(api, session.workspace_id)
    _apply(api, begin["editSessionId"])

    with pytest.raises(RuntimeApiError) as exc_info:
        _apply(api, begin["editSessionId"], revision=0, command_id="move-2")

    assert exc_info.value.code == "version_conflict"
    assert len(module.place_calls) == 1


def test_layout_edit_apply_replays_completed_command_before_revision_validation(
    monkeypatch,
    tmp_path,
):
    api, session, _step, module, _flow_calls = _open_api(monkeypatch, tmp_path)
    begin = _begin(api, session.workspace_id)
    first = _apply(api, begin["editSessionId"])

    replay = _apply(api, begin["editSessionId"], revision=0)

    assert replay == first
    assert len(module.place_calls) == 1


def test_layout_edit_apply_allows_preserve_orientation_for_existing_instance(
    monkeypatch,
    tmp_path,
):
    api, session, _step, module, _flow_calls = _open_api(monkeypatch, tmp_path)
    begin = _begin(api, session.workspace_id)

    result = api.layout_edit_apply(
        LayoutEditApplyRequest(
            edit_session_id=begin["editSessionId"],
            command_id="move-with-preserved-orient",
            base_revision=0,
            operation={
                "kind": "place_instance",
                "instName": "u_sram_0",
                "llx": 1200,
                "lly": 3400,
                "orient": "",
                "placementStatus": "preserve",
                "createIfMissing": False,
            },
        )
    )

    assert result["revision"] == 1
    assert module.place_calls[0]["orient"] == ""
