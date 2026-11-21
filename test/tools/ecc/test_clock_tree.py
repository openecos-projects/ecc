import json
from pathlib import Path
from types import SimpleNamespace

import pytest

from chipcompiler.data import PDK, Parameters, StepEnum, Workspace
from chipcompiler.tools.ecc.clock_tree import (
    ClockTreeCaptureError,
    _select_typ_liberty,
    _select_typical_spef,
    capture_filler_clock_tree,
)
from chipcompiler.utility.threads import thread_budget


def _sta_config(tmp_path: Path, *, typ_temperature: int = 25) -> tuple[Path, Path]:
    liberty = tmp_path / "typ.lib"
    liberty.write_text("library (typ) {}\n", encoding="utf-8")
    config = tmp_path / "sta_ecc.json"
    config.write_text(
        json.dumps(
            {
                "liberty": [
                    {"corner": "MAX", "temperature": 125, "path": [str(liberty)]},
                    {
                        "corner": "TYP",
                        "temperature": typ_temperature,
                        "path": [str(liberty)],
                    },
                ]
            }
        ),
        encoding="utf-8",
    )
    return config, liberty


def _write_spef(path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text('*SPEF "IEEE 1481-1998"\n*DESIGN "gcd"\n*T_UNIT 1 NS\n', encoding="utf-8")


def test_select_typ_liberty_does_not_take_the_first_corner(tmp_path):
    config, liberty = _sta_config(tmp_path)

    paths, corner, temperature = _select_typ_liberty(config)

    assert paths == [str(liberty)]
    assert corner == "TYP"
    assert temperature == 25.0


def test_select_typ_liberty_rejects_temperature_mismatch(tmp_path):
    config, _liberty = _sta_config(tmp_path, typ_temperature=0)

    with pytest.raises(ClockTreeCaptureError, match="exactly one TYP Liberty at 25°C"):
        _select_typ_liberty(config)


def test_select_typical_spef_requires_exact_corner_and_temperature(tmp_path):
    _write_spef(tmp_path / "spef_writer" / "gcd_Cworst_125C.spef")
    _write_spef(tmp_path / "spef_writer" / "gcd_TYPICAL_125C.spef")
    expected = tmp_path / "spef_writer" / "gcd_TYPICAL_25C.spef"
    _write_spef(expected)

    assert _select_typical_spef(tmp_path, 25.0) == expected


def test_capture_filler_clock_tree_runs_rcx_then_ista_and_attaches_provenance(tmp_path):
    sta_config, _liberty = _sta_config(tmp_path)
    from chipcompiler.data.workspace.tool_configs import tool_config

    configs_dir = Path(__file__).resolve().parents[3] / "chipcompiler/tools/ecc/configs"
    rcx_config = tmp_path / "rcx_ecc.json"
    rcx_payload = tool_config(configs_dir, rcx_config.name, PDK()) | {
        "mapping_file": str(tmp_path / "layers.map"),
        "corners": [{"name": "TYPICAL", "process_file": str(tmp_path / "typ.itf")}],
    }
    rcx_config.write_text(json.dumps(rcx_payload))
    sdc = tmp_path / "gcd.sdc"
    sdc.write_text("create_clock -period 10 clk\n", encoding="utf-8")
    workspace = Workspace(
        directory=tmp_path,
        pdk=PDK(name="fixture", sdc=sdc),
        parameters=Parameters(
            path=tmp_path / "home" / "params.toml",
            data={"geometry": {"clock_tree": True}},
        ),
        config={StepEnum.STA.value: sta_config, StepEnum.RCX.value: rcx_config},
    )
    step = SimpleNamespace(
        name=StepEnum.FILLER.value,
        directory=tmp_path / "filler_ecc",
        data=SimpleNamespace(
            steps={StepEnum.FILLER.value: tmp_path / "filler_ecc" / "data" / "mj"}
        ),
    )

    class FakeNative:
        def __init__(self):
            self.calls = []

        def lib_init(self, **kwargs):
            self.calls.append(("lib_init", kwargs))
            return True

        def sdc_init(self, path):
            self.calls.append(("sdc_init", path))
            return True

        def spef_init(self, path):
            self.calls.append(("spef_init", path))
            return True

        def init_sta(self, **kwargs):
            self.calls.append(("init_sta", kwargs))
            return True

        def run_sta(self):
            self.calls.append(("run_sta",))
            return True

        def sta_clock_graph(self):
            self.calls.append(("sta_clock_graph",))
            return {"clocks": [{"name": "clk", "nodes": [], "edges": []}], "diagnostics": []}

        def destroy_sta(self):
            self.calls.append(("destroy_sta",))
            return True

    class FakeModule:
        def __init__(self):
            self.calls = []
            self.native = FakeNative()

        def get_ecc(self):
            return self.native

        def init_rcx(self, config):
            self.calls.append(("init_rcx", config))
            payload = json.loads(Path(config).read_text(encoding="utf-8"))
            assert payload == rcx_payload | {
                "thread_num": thread_budget(default=64),
                "output": str(tmp_path / "filler_ecc/data/clock_tree/rcx"),
            }
            _write_spef(Path(payload["output"]) / "spef_writer" / "gcd_TYPICAL_25C.spef")
            return True

        def run_rcx(self):
            self.calls.append(("run_rcx",))
            return True

        def destroy_rcx(self):
            self.calls.append(("destroy_rcx",))
            return True

    module = FakeModule()

    graph = capture_filler_clock_tree(workspace, step, module)

    assert module.calls == [
        (
            "init_rcx",
            tmp_path / "filler_ecc" / "data" / "clock_tree" / "rcx_config.json",
        ),
        ("run_rcx",),
        ("destroy_rcx",),
    ]
    assert [call[0] for call in module.native.calls] == [
        "lib_init",
        "sdc_init",
        "spef_init",
        "init_sta",
        "run_sta",
        "sta_clock_graph",
        "destroy_sta",
    ]
    assert module.native.calls[3][1]["config_dict"]["-timing_corner"] == "TYP"
    assert module.native.calls[3][1]["config_dict"]["-thread_number"] == str(
        thread_budget(default=64)
    )
    assert graph is not None
    assert graph["stage"] == "filler"
    assert graph["analysis_source"] == "ista_typical"
    assert graph["rc_corner"] == "TYPICAL"
    assert graph["liberty_corner"] == "TYP"
    assert graph["temperature_c"] == 25.0
    assert "SPEF=gcd_TYPICAL_25C.spef" in graph["diagnostics"][-1]


def test_capture_filler_clock_tree_honors_ecc_threads(tmp_path, monkeypatch):
    sta_config, _liberty = _sta_config(tmp_path)
    rcx_config = tmp_path / "rcx_ecc.json"
    rcx_config.write_text(json.dumps({"thread_num": 64}), encoding="utf-8")
    sdc = tmp_path / "gcd.sdc"
    sdc.write_text("create_clock -period 10 clk\n", encoding="utf-8")
    monkeypatch.setenv("ECC_THREADS", "5")
    workspace = Workspace(
        directory=tmp_path,
        pdk=PDK(name="fixture", sdc=sdc),
        parameters=Parameters(
            path=tmp_path / "home" / "params.toml",
            data={"geometry": {"clock_tree": True}},
        ),
        config={StepEnum.STA.value: sta_config, StepEnum.RCX.value: rcx_config},
    )
    step = SimpleNamespace(
        name=StepEnum.FILLER.value,
        directory=tmp_path / "filler_ecc",
        data=SimpleNamespace(steps={}),
    )

    class FakeNative:
        def __init__(self):
            self.calls = []

        def lib_init(self, **_kwargs):
            return True

        def sdc_init(self, _path):
            return True

        def spef_init(self, _path):
            return True

        def init_sta(self, **kwargs):
            self.calls.append(kwargs)
            return True

        def run_sta(self):
            return True

        def sta_clock_graph(self):
            return {"clocks": [], "diagnostics": []}

        def destroy_sta(self):
            return True

    class FakeModule:
        def __init__(self):
            self.rcx_thread_num = None
            self.native = FakeNative()

        def get_ecc(self):
            return self.native

        def init_rcx(self, config):
            payload = json.loads(Path(config).read_text(encoding="utf-8"))
            self.rcx_thread_num = payload["thread_num"]
            _write_spef(Path(payload["output"]) / "spef_writer" / "gcd_TYPICAL_25C.spef")
            return True

        def run_rcx(self):
            return True

        def destroy_rcx(self):
            return True

    module = FakeModule()
    capture_filler_clock_tree(workspace, step, module)

    assert module.rcx_thread_num == 5
    assert module.native.calls[0]["config_dict"]["-thread_number"] == "5"
