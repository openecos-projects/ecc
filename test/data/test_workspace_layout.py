"""Behavior tests for the typed WorkspaceStep layout and its migration shim.

These pin the transitional dict-compatibility contract (AC-3): each path group
is a typed dataclass that ALSO behaves like its former dict, so existing readers
keep working unchanged while the migration proceeds. The shim is removed once all
readers use attribute access; the attribute-access assertions here survive that.
"""

from __future__ import annotations

from pathlib import Path

from chipcompiler.data import (
    EccStep,
    OriginDesign,
    OutputPaths,
    StepData,
    StepInput,
    SubflowState,
    Workspace,
    WorkspaceStep,
    WorkspaceStepBase,
    YosysStep,
)
from chipcompiler.tools.ecc import builder as ecc_builder
from chipcompiler.tools.yosys import builder as yosys_builder


def test_workspace_step_is_base_alias():
    assert WorkspaceStep is WorkspaceStepBase
    assert issubclass(YosysStep, WorkspaceStep)
    assert issubclass(EccStep, WorkspaceStep)


def test_variants_are_isinstance_of_base():
    assert isinstance(YosysStep(), WorkspaceStep)
    assert isinstance(EccStep(), WorkspaceStep)


def test_result_field_is_gone():
    assert not hasattr(WorkspaceStep(), "result")


def test_get_read_matches_legacy_dict_defaults():
    output = OutputPaths(dir=Path("/d"), verilog=Path("/v.v"))
    assert output.get("verilog") == Path("/v.v")
    assert output.get("gds") is None
    assert output.get("gds", "") == ""
    assert output.get("gds", []) == []


def test_subscript_read_and_contains():
    output = OutputPaths(dir=Path("/d"))
    assert output["dir"] == Path("/d")
    assert "dir" in output
    assert "gds" not in output


def test_subscript_write_adds_key():
    output = OutputPaths(dir=Path("/d"))
    output["spef"] = [Path("/a.spef")]
    assert output["spef"] == [Path("/a.spef")]
    assert "spef" in output
    assert output.spef == [Path("/a.spef")]


def test_def_keyword_key_round_trips_to_attribute():
    output = OutputPaths(dir=Path("/d"))
    output["def"] = Path("/x.def")
    assert output["def"] == Path("/x.def")
    assert output.def_ == output["def"]
    assert "def" in dict(output)
    assert "def_" not in dict(output)


def test_dict_projects_only_assigned_keys():
    output = OutputPaths(dir=Path("/d"), verilog=Path("/v.v"))
    assert dict(output) == {"dir": Path("/d"), "verilog": Path("/v.v")}
    # Unset typed fields read as None via attribute but are not projected.
    assert output.gds is None
    assert "gds" not in dict(output)


def test_values_and_items_match_projection():
    output = OutputPaths(dir=Path("/d"), verilog=Path("/v.v"))
    assert sorted(str(v) for v in output.values()) == ["/d", "/v.v"]
    assert dict(output.items()) == {"dir": Path("/d"), "verilog": Path("/v.v")}
    assert set(output.keys()) == {"dir", "verilog"}
    assert len(output) == 2


def test_iteration_yields_legacy_keys():
    output = OutputPaths(dir=Path("/d"))
    output["def"] = Path("/x.def")
    assert list(output) == ["dir", "def"]


def test_no_value_coercion_str_stays_str():
    # Tools/tests sometimes seed a str; the shim must not coerce it to Path.
    output = OutputPaths()
    output["dir"] = "/some/str/path"
    assert output["dir"] == "/some/str/path"
    assert isinstance(output["dir"], str)


def test_sizer_empty_db_stays_empty_string():
    output = OutputPaths(db="")
    assert output["db"] == ""
    assert output.db == ""
    assert "db" in output


def test_whole_dict_assignment_is_normalized_to_group():
    # A plain dict assigned to a group is normalized into the typed group via
    # __setattr__ (the transitional contract; pyright cannot express dict->group).
    step = EccStep(name="Floorplan")
    step.output = {"dir": Path("/d"), "def": Path("/x.def"), "db": ""}  # type: ignore[assignment]
    assert isinstance(step.output, OutputPaths)
    assert dict(step.output) == {"dir": Path("/d"), "def": Path("/x.def"), "db": ""}
    assert step.output.def_ == step.output["def"]


def test_input_dict_assignment_normalized():
    step = EccStep(name="Floorplan")
    step.input = {"def": Path("/i.def"), "verilog": Path("/i.v"), "db": None}  # type: ignore[assignment]
    assert isinstance(step.input, StepInput)
    assert step.input["def"] == Path("/i.def")
    assert step.input.verilog == Path("/i.v")


def test_data_supports_dynamic_step_keyed_directories():
    # ecc data is keyed by StepEnum values, some containing spaces.
    step = EccStep(name="Timing optimization")
    step.data = StepData(dir=Path("/data"))
    step.data["Timing optimization"] = Path("/data/to")
    assert step.data["Timing optimization"] == Path("/data/to")
    assert step.data.get("Timing optimization") == Path("/data/to")
    assert step.data.get("dir") == Path("/data")


def test_dict_subflow_round_trips():
    # Live path: the subflow modules do dict(self.workspace_step.subflow).
    step = EccStep(name="Floorplan")
    step.subflow = SubflowState(path=Path("/s/subflow.json"), steps=[])
    materialized = dict(step.subflow)
    assert materialized == {"path": Path("/s/subflow.json"), "steps": []}
    # A later mutation to steps is visible through the mapping too.
    step.subflow["steps"].append({"name": "load data"})
    assert dict(step.subflow)["steps"] == [{"name": "load data"}]


def test_data_values_iteration_for_build_step_space():
    # ecc build_step_space iterates step.data.values() to mkdir each directory.
    step = EccStep(name="Floorplan")
    step.data = StepData(dir=Path("/data"))
    step.data["place"] = Path("/data/pl")
    assert sorted(str(v) for v in step.data.values()) == ["/data", "/data/pl"]


def test_build_step_returns_correct_variant(tmp_path):
    workspace = Workspace(
        directory=tmp_path,
        design=OriginDesign(name="gcd", top_module="gcd"),
    )

    yosys_step = yosys_builder.build_step(
        workspace, "Synthesis", None, tmp_path / "in.v"
    )
    assert isinstance(yosys_step, YosysStep)
    assert isinstance(yosys_step, WorkspaceStep)

    ecc_step = ecc_builder.build_step(
        workspace, "Floorplan", tmp_path / "i.def", tmp_path / "i.v"
    )
    assert isinstance(ecc_step, EccStep)
    assert isinstance(ecc_step, WorkspaceStep)
