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

    with pytest.raises(ClockTreeCaptureError, match="TYP/TYPICAL Liberty at 25°C"):
        _select_typ_liberty(config)


@pytest.mark.parametrize("rc_corner", ["TYPICAL", "Cworst"])
def test_select_typ_liberty_prefers_the_matching_rc_group(tmp_path, rc_corner):
    config, fallback = _sta_config(tmp_path)
    specific = tmp_path / "specific.lib"
    specific.write_text("library(specific) {}\n")
    payload = json.loads(config.read_text())
    payload["liberty"].append(
        {"corner": "TYP", "temperature": 25, "rc_corner": rc_corner, "path": [str(specific)]}
    )
    config.write_text(json.dumps(payload))

    expected = specific if rc_corner == "TYPICAL" else fallback
    assert _select_typ_liberty(config) == ([str(expected)], "TYP", 25.0)


def test_select_typ_liberty_rejects_ambiguous_rc_groups(tmp_path):
    config, _liberty = _sta_config(tmp_path)
    payload = json.loads(config.read_text())
    group = payload["liberty"][1] | {"rc_corner": "TYPICAL"}
    payload["liberty"] += [group, group]
    config.write_text(json.dumps(payload))

    with pytest.raises(ClockTreeCaptureError, match="Ambiguous STA Liberty groups for TYP/TYPICAL"):
        _select_typ_liberty(config)


def test_select_typical_spef_requires_exact_corner_and_temperature(tmp_path):
    _write_spef(tmp_path / "spef_writer" / "gcd_Cworst_125C.spef")
    _write_spef(tmp_path / "spef_writer" / "gcd_TYPICAL_125C.spef")
    expected = tmp_path / "spef_writer" / "gcd_TYPICAL_25C.spef"
    _write_spef(expected)

    assert _select_typical_spef(tmp_path, 25.0) == expected


@pytest.mark.parametrize("rc_specific", [False, True])
def test_capture_filler_clock_tree_runs_rcx_then_ista_and_attaches_provenance(
    tmp_path, rc_specific
):
    sta_config, liberty = _sta_config(tmp_path)
    if rc_specific:
        liberty = tmp_path / "typical.lib"
        liberty.write_text("library(typical) {}\n")
        payload = json.loads(sta_config.read_text())
        payload["liberty"].append(
            {"corner": "TYP", "temperature": 25, "rc_corner": "TYPICAL", "path": [str(liberty)]}
        )
        sta_config.write_text(json.dumps(payload))
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
                "output": str(tmp_path / "filler_ecc/data/clock_tree/rcx")
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
    assert module.native.calls[0] == ("lib_init", {"lib_paths": [str(liberty)]})
    assert module.native.calls[3][1]["config_dict"]["-timing_corner"] == "TYP"
    assert graph is not None
    assert graph["stage"] == "filler"
    assert graph["analysis_source"] == "ista_typical"
    assert graph["rc_corner"] == "TYPICAL"
    assert graph["liberty_corner"] == "TYP"
    assert graph["temperature_c"] == 25.0
    assert "SPEF=gcd_TYPICAL_25C.spef" in graph["diagnostics"][-1]
