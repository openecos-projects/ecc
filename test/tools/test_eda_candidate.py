import json
from pathlib import Path
from types import SimpleNamespace

from chipcompiler.data.candidate_materialization import materialize_candidate_config
from chipcompiler.tools import eda


def _write_json(path: Path, data: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data), encoding="utf-8")


def test_tool_runner_reapplies_candidate_overlay_after_builder_refresh(monkeypatch, tmp_path):
    config_path = tmp_path / "config" / "dreamplace.json"
    _write_json(config_path, {"target_density": 0.8})
    workspace = SimpleNamespace(
        directory=str(tmp_path),
        config={"dreamplace": config_path},
        pdk=SimpleNamespace(),
        logger=SimpleNamespace(),
        flow=SimpleNamespace(data={"steps": [{"name": "place", "tool": "dreamplace"}]}),
    )
    step = SimpleNamespace(name="place", tool="dreamplace")
    materialize_candidate_config(
        workspace,
        "place",
        [{"knob_id": "place.target_density", "value": 0.65}],
        candidate_id="place-rerun-001",
    )
    consumed = []

    def build_step_config(_workspace, _step):
        _write_json(config_path, {"target_density": 0.2})

    def run_step(workspace, step, ecc_module):
        del workspace, step
        consumed.append(json.loads(config_path.read_text(encoding="utf-8"))["target_density"])
        return ecc_module

    tool = SimpleNamespace(build_step_config=build_step_config, run_step=run_step)
    monkeypatch.setattr(eda, "load_eda_module", lambda *_args, **_kwargs: tool)
    monkeypatch.setattr(eda, "log_workspace_step", lambda *_args, **_kwargs: None)

    assert eda.run_step(workspace, step, ecc_module=True) is True
    assert consumed == [0.65]


def test_legalization_runner_reapplies_real_dreamplace_overlay(monkeypatch, tmp_path):
    config_path = tmp_path / "config" / "dreamplace.json"
    _write_json(config_path, {"bndry_padding_x": 0})
    workspace = SimpleNamespace(
        directory=str(tmp_path),
        config={"dreamplace": config_path},
        pdk=SimpleNamespace(),
        logger=SimpleNamespace(),
        flow=SimpleNamespace(data={"steps": [{"name": "legalization", "tool": "dreamplace"}]}),
    )
    step = SimpleNamespace(name="legalization", tool="dreamplace")
    materialize_candidate_config(
        workspace,
        "legalization",
        [{"knob_id": "legalization.bndry_padding_x", "value": 16}],
        candidate_id="legalization-rerun-001",
    )
    consumed = []

    def build_step_config(_workspace, _step):
        _write_json(config_path, {"bndry_padding_x": 0})

    def run_step(workspace, step, ecc_module):
        del workspace, step
        consumed.append(json.loads(config_path.read_text(encoding="utf-8"))["bndry_padding_x"])
        return ecc_module

    tool = SimpleNamespace(build_step_config=build_step_config, run_step=run_step)
    monkeypatch.setattr(eda, "load_eda_module", lambda *_args, **_kwargs: tool)
    monkeypatch.setattr(eda, "log_workspace_step", lambda *_args, **_kwargs: None)

    assert eda.run_step(workspace, step, ecc_module=True) is True
    assert consumed == [16]
