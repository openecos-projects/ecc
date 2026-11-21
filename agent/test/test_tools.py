import json
import os
from contextlib import contextmanager
from pathlib import Path
from types import SimpleNamespace
from typing import Any

import pytest

from agent import tools as eda
from agent.data import parameter_runtime_observer as runtime_observer
from agent.data.candidate_materialization import materialize_candidate_config
from test.flow_fixture import step_fields


def _ns(**kwargs: object) -> Any:
    return SimpleNamespace(**kwargs)


def _write_json(path: Path, data: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data), encoding="utf-8")


class _Scalar:
    def __init__(self, value):
        self.value = value

    def item(self):
        return self.value


def _placement_workspace(tmp_path: Path, logger: object) -> Any:
    from chipcompiler.data.workspace.config import save_workspace_config

    config_path = tmp_path / "config" / "dreamplace_ecc.json"
    _write_json(config_path, {"target_density": 0.8})
    assert save_workspace_config(tmp_path, {"core": {"utilitization": 0.6}})
    return _ns(
        directory=str(tmp_path),
        config={"dreamplace": config_path},
        parameters=_ns(path=tmp_path / "home" / "params.toml"),
        pdk=_ns(),
        logger=logger,
        flow=_ns(
            data={
                "schema_version": 3,
                "steps": [
                    {
                        "name": "placement",
                        "tool": "dreamplace",
                        **step_fields("placement", "dreamplace"),
                    }
                ],
            }
        ),
    )


def test_tool_runner_restores_candidate_step_values_before_the_step_build(monkeypatch, tmp_path):
    from chipcompiler.data.parameter import load_parameter
    from chipcompiler.data.step_parameters import step_config_patch
    from chipcompiler.data.workspace.config import save_workspace_config

    workspace = _placement_workspace(tmp_path, _ns())
    step = _ns(name="placement", tool="dreamplace", directory=tmp_path / "placement_dreamplace")
    step_config = step.directory / "config" / "dreamplace_ecc.json"
    materialize_candidate_config(
        workspace,
        "placement",
        [{"knob_id": "place.target_density", "value": 0.65}],
        candidate_id="place-rerun-001",
    )
    # A refresh between materialization and the run drops the step value.
    assert save_workspace_config(tmp_path, {"core": {"utilitization": 0.6}})
    consumed = []

    def build_step_config(workspace, step):
        # Mirrors the DreamPlace build: baseline plus the step's stored values.
        stored = load_parameter(workspace.parameters.path).data
        config = json.loads(Path(workspace.config["dreamplace"]).read_text(encoding="utf-8"))
        _write_json(step_config, config | step_config_patch(stored, step.name)["dreamplace"])

    def run_step(workspace, step, ecc_module):
        del workspace, step
        consumed.append(json.loads(step_config.read_text(encoding="utf-8")))
        return ecc_module

    tool = _ns(build_step_config=build_step_config, run_step=run_step)
    monkeypatch.setattr(eda, "load_eda_module", lambda *_args, **_kwargs: tool)
    monkeypatch.setattr(eda, "log_workspace_step", lambda *_args, **_kwargs: None)

    assert eda.run_step(workspace, step, ecc_module=True) is True
    assert consumed == [{"target_density": 0.65}]


def test_agent_sizer_runner_isolates_loader_environment(monkeypatch, tmp_path):
    workspace = _ns(
        directory=str(tmp_path),
        config={},
        logger=_ns(),
        flow=_ns(
            data={
                "schema_version": 3,
                "steps": [
                    {
                        "name": "timing_optimization",
                        "tool": "sizer",
                        **step_fields("timing_optimization", "sizer"),
                    }
                ],
            }
        ),
    )
    step = _ns(name="timing_optimization", tool="sizer")
    runtime_root = tmp_path / "sizer"
    executable = runtime_root / "bin" / "Sizer"
    executable.parent.mkdir(parents=True)
    executable.write_text("#!/bin/sh\n", encoding="utf-8")
    executable.chmod(0o755)
    observed = {}

    def run_step(**_kwargs):
        observed.update(
            LD_LIBRARY_PATH=os.environ.get("LD_LIBRARY_PATH"),
            LD_PRELOAD=os.environ.get("LD_PRELOAD"),
        )
        return True

    tool = _ns(build_step_config=lambda *_args: None, run_step=run_step)
    monkeypatch.setattr(eda, "load_eda_module", lambda *_args, **_kwargs: tool)
    monkeypatch.setattr(eda, "log_workspace_step", lambda *_args, **_kwargs: None)
    monkeypatch.setattr(eda, "reapply_materialized_candidate_config", lambda *_args: None)
    monkeypatch.setattr(eda, "run_with_parameter_observation", lambda *_args: _args[-1]())
    monkeypatch.setenv("CHIPCOMPILER_ECC_SIZER_ROOT", str(runtime_root))
    monkeypatch.setenv("LD_LIBRARY_PATH", "/packaged/lib")
    monkeypatch.setenv("LD_PRELOAD", "/packaged/preload.so")

    assert eda.run_step(workspace, step) is True
    assert observed == {"LD_LIBRARY_PATH": None, "LD_PRELOAD": None}
    assert os.environ["LD_LIBRARY_PATH"] == "/packaged/lib"
    assert os.environ["LD_PRELOAD"] == "/packaged/preload.so"


def test_tool_runner_owns_candidate_runtime_report(monkeypatch, tmp_path):
    workspace = _placement_workspace(tmp_path, _ns(exception=lambda *_args, **_kwargs: None))
    step = _ns(name="placement", tool="dreamplace")
    materialize_candidate_config(
        workspace,
        "placement",
        [{"knob_id": "place.target_density", "value": 0.65}],
        candidate_id="place-rerun-observed",
    )
    recorder = runtime_observer.DreamplaceRecorder(
        patch={"knob_id": "place.target_density", "value": 0.65}
    )

    def run_step(**_kwargs):
        recorder.engine = _ns(
            params=_ns(target_density=0.65),
            placer=_ns(data_collections=_ns(target_density=_Scalar(0.65))),
        )
        recorder.ppa = {"iteration": 3}
        recorder.probe["density_operator_call_count"] = 2
        recorder.probe["target_density"] = 0.65
        recorder.probe["density_tensor_value"] = 0.65
        return True

    tool = _ns(build_step_config=lambda *_args: None, run_step=run_step)
    monkeypatch.setattr(eda, "load_eda_module", lambda *_args, **_kwargs: tool)
    monkeypatch.setattr(eda, "log_workspace_step", lambda *_args, **_kwargs: None)

    @contextmanager
    def capture(_patch):
        yield recorder

    monkeypatch.setattr(runtime_observer, "_capture_dreamplace", capture)

    assert eda.run_step(workspace, step, ecc_module=True) is True
    report = json.loads((tmp_path / "analysis" / "parameter_runtime_report.v2.json").read_text())
    assert report["tool"]["revision"] == "ecc.agent.dreamplace_parameter_observer.v3"
    assert report["status"] == "effective"
    assert report["observation"]["density_operator_call_count"] == 2


def test_tool_runner_without_receipts_uses_the_shared_tool_contract(monkeypatch, tmp_path):
    workspace = _ns(directory=tmp_path, config={}, logger=None)
    step = _ns(name="routing", tool="ecc")
    calls = []
    tool = _ns(
        build_step_config=lambda *_args: calls.append("build"),
        run_step=lambda **_kwargs: calls.append("run") or True,
    )
    monkeypatch.setattr(eda, "load_eda_module", lambda *_args, **_kwargs: tool)
    monkeypatch.setattr(eda, "log_workspace_step", lambda *_args: calls.append("log"))

    assert eda.run_step(workspace, step) is True
    assert calls == ["build", "log", "run"]


@pytest.mark.parametrize("workers", [1, 2, 3, 4])
def test_candidate_sta_uses_shared_parallel_dispatch(monkeypatch, tmp_path, workers):
    from chipcompiler.tools.ecc import runner as shared_runner
    from chipcompiler.tools.ecc import sta_parallel as shared_sta

    calls = []
    config_path = tmp_path / "sta.json"
    _write_json(
        config_path,
        {
            "max_parallel_corners": workers,
            "signoff": [{"MAX": ["Cworst", "RCworst"]}, {"MIN": ["Cbest", "RCbest"]}],
        },
    )
    workspace = _ns(
        directory=tmp_path / ".agent" / "candidates" / "one",
        logger=None,
        config={"sta": config_path},
    )
    step = _ns(name="sta", tool="ecc")
    tool = _ns(
        build_step_config=lambda *_: None,
        run_step=shared_runner.run_step,
    )
    monkeypatch.setattr(os, "cpu_count", lambda: 8)
    monkeypatch.setattr(os, "sched_getaffinity", lambda _pid: set(range(8)), raising=False)
    monkeypatch.setattr(eda, "load_eda_module", lambda *_args, **_kwargs: tool)
    monkeypatch.setattr(eda, "log_workspace_step", lambda *_: None)
    monkeypatch.setattr(shared_sta, "sta_workers", lambda *_args: workers)
    monkeypatch.setattr(
        shared_sta,
        "run_parallel_sta",
        lambda _workspace, _step, _module, count: calls.append(count) or True,
    )
    monkeypatch.setattr(
        shared_runner,
        "run_sta",
        lambda **_kwargs: calls.append("serial") or True,
    )

    assert eda.run_step(workspace, step) is True
    assert calls == (["serial"] if workers == 1 else [workers])
