import json
from contextlib import contextmanager
from pathlib import Path
from types import SimpleNamespace

from agent import tools as eda
from agent.data import parameter_runtime_observer as runtime_observer
from agent.data.candidate_materialization import materialize_candidate_config


def _write_json(path: Path, data: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data), encoding="utf-8")


class _Scalar:
    def __init__(self, value):
        self.value = value

    def item(self):
        return self.value


def test_tool_runner_reapplies_candidate_overlay_after_builder_refresh(monkeypatch, tmp_path):
    config_path = tmp_path / "config" / "dreamplace_ecc.json"
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


def test_tool_runner_owns_candidate_runtime_report(monkeypatch, tmp_path):
    config_path = tmp_path / "config" / "dreamplace_ecc.json"
    _write_json(config_path, {"target_density": 0.8})
    workspace = SimpleNamespace(
        directory=str(tmp_path),
        config={"dreamplace": config_path},
        pdk=SimpleNamespace(),
        logger=SimpleNamespace(exception=lambda *_args, **_kwargs: None),
        flow=SimpleNamespace(data={"steps": [{"name": "place", "tool": "dreamplace"}]}),
    )
    step = SimpleNamespace(name="place", tool="dreamplace")
    materialize_candidate_config(
        workspace,
        "place",
        [{"knob_id": "place.target_density", "value": 0.65}],
        candidate_id="place-rerun-observed",
    )
    recorder = runtime_observer.DreamplaceRecorder(
        patch={"knob_id": "place.target_density", "value": 0.65}
    )

    def run_step(**_kwargs):
        recorder.engine = SimpleNamespace(
            params=SimpleNamespace(target_density=0.65),
            placer=SimpleNamespace(data_collections=SimpleNamespace(target_density=_Scalar(0.65))),
        )
        recorder.ppa = {"iteration": 3}
        recorder.probe["density_operator_call_count"] = 2
        return True

    tool = SimpleNamespace(build_step_config=lambda *_args: None, run_step=run_step)
    monkeypatch.setattr(eda, "load_eda_module", lambda *_args, **_kwargs: tool)
    monkeypatch.setattr(eda, "log_workspace_step", lambda *_args, **_kwargs: None)

    @contextmanager
    def capture(_patch):
        yield recorder

    monkeypatch.setattr(runtime_observer, "_capture_dreamplace", capture)

    assert eda.run_step(workspace, step, ecc_module=True) is True
    report = json.loads((tmp_path / "analysis" / "parameter_runtime_report.v1.json").read_text())
    assert report["tool"]["revision"] == "ecc.agent.dreamplace_parameter_observer.v1"
    assert report["activation"]["status"] == "used"
    assert report["consumer_observation"]["density_operator_call_count"] == 2


def test_legalization_runner_reapplies_real_dreamplace_overlay(monkeypatch, tmp_path):
    config_path = tmp_path / "config" / "dreamplace_ecc.json"
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
