"""Behavior tests for the typed WorkspaceStep layout.

These pin the typed attribute contract of the step path groups: the step
hierarchy (base + yosys/ecc variants), the ``"def"`` -> ``def_`` rename, the
place-and-route ``data.steps`` mapping with its ``workdir_for`` /
``iter_directories`` helpers, and that field values are never coerced.
"""

from pathlib import Path

import pytest

from chipcompiler.data import (
    EccData,
    EccOutput,
    EccReport,
    EccStep,
    OriginDesign,
    OutputPaths,
    Workspace,
    WorkspaceStep,
    WorkspaceStepBase,
    YosysOutput,
    YosysStep,
)
from chipcompiler.data.workspace import log_workspace_step, step_group_to_dict
from chipcompiler.tools.ecc import builder as ecc_builder
from chipcompiler.tools.yosys import builder as yosys_builder
from chipcompiler.utility.log import Logger


def test_workspace_step_is_base_alias():
    assert WorkspaceStep is WorkspaceStepBase
    assert issubclass(YosysStep, WorkspaceStep)
    assert issubclass(EccStep, WorkspaceStep)


def test_variants_are_isinstance_of_base():
    assert isinstance(YosysStep(), WorkspaceStep)
    assert isinstance(EccStep(), WorkspaceStep)


def test_result_field_is_gone():
    assert not hasattr(WorkspaceStep(), "result")


def test_unset_group_fields_default_to_none():
    output = EccOutput(dir=Path("/d"), verilog=Path("/v.v"))
    assert output.dir == Path("/d")
    assert output.verilog == Path("/v.v")
    assert output.gds is None
    assert output.spef == []


def test_def_keyword_is_exposed_as_def_attribute():
    output = OutputPaths(def_=Path("/x.def"))
    assert output.def_ == Path("/x.def")


def test_no_value_coercion_str_stays_str():
    # `db` legitimately holds a str (sizer uses ""); the layout must not coerce it.
    output = EccOutput(db="/some/str/path")
    assert output.db == "/some/str/path"
    assert isinstance(output.db, str)


def test_sizer_empty_db_stays_empty_string():
    output = EccOutput(db="")
    assert output.db == ""


def test_data_supports_dynamic_step_keyed_directories():
    # ecc data holds per-step working dirs keyed by StepEnum values (some with
    # spaces) in an explicit `steps` mapping; workdir_for falls back to `dir`.
    step = EccStep(
        name="Timing optimization",
        data=EccData(dir=Path("/data"), steps={"Timing optimization": Path("/data/to")}),
    )
    assert step.data.steps["Timing optimization"] == Path("/data/to")
    assert step.data.workdir_for("Timing optimization") == Path("/data/to")
    assert step.data.workdir_for("unknown step") == Path("/data")
    assert step.data.dir == Path("/data")


def test_data_iter_directories_for_build_step_space():
    # ecc build_step_space iterates step.data.iter_directories() to mkdir each.
    step = EccStep(
        name="Floorplan",
        data=EccData(dir=Path("/data"), steps={"place": Path("/data/pl")}),
    )
    assert sorted(str(v) for v in step.data.iter_directories()) == ["/data", "/data/pl"]


def test_build_step_returns_correct_variant(tmp_path):
    workspace = Workspace(
        directory=tmp_path,
        design=OriginDesign(name="gcd", top_module="gcd"),
    )

    yosys_step = yosys_builder.build_step(workspace, "Synthesis", None, tmp_path / "in.v")
    assert isinstance(yosys_step, YosysStep)
    assert isinstance(yosys_step, WorkspaceStep)

    ecc_step = ecc_builder.build_step(workspace, "Floorplan", tmp_path / "i.def", tmp_path / "i.v")
    assert isinstance(ecc_step, EccStep)
    assert isinstance(ecc_step, WorkspaceStep)


def test_group_to_dict_renames_def_and_drops_unset_inherited_fields():
    # def_ -> "def"; a populated ecc output emits all its keys incl. base db/spef.
    output = EccOutput(dir=Path("/d"), def_=Path("/x.def"), db=Path("/db"), spef=[Path("/a")])
    projected = step_group_to_dict(output)
    assert projected["def"] == Path("/x.def")
    assert "def_" not in projected
    assert projected["db"] == Path("/db")
    assert projected["spef"] == [Path("/a")]

    # A synthesis output never sets db (inherited from base) -> it is NOT emitted.
    yosys_output = YosysOutput(dir=Path("/d"), verilog=Path("/v"))
    projected = step_group_to_dict(yosys_output)
    assert "db" not in projected
    assert "gds" not in projected  # ecc-only, absent on the yosys shape
    assert projected == {"dir": Path("/d"), "verilog": Path("/v")}


def test_group_to_dict_flattens_data_steps_and_projects_nested_sta():
    data = EccData(dir=Path("/d"), steps={"Timing optimization": Path("/d/to")})
    projected = step_group_to_dict(data)
    # per-step dirs are flattened to top-level keys; "steps" itself is dropped.
    assert projected == {"dir": Path("/d"), "Timing optimization": Path("/d/to")}

    report = EccReport(dir=Path("/r"), sta={"dir": Path("/r/sta")})
    projected = step_group_to_dict(report)
    # the sta mapping passes through as a nested dict.
    assert projected == {"dir": Path("/r"), "sta": {"dir": Path("/r/sta")}}


def _shape_keys(step):
    return {
        group: sorted(step_group_to_dict(getattr(step, group)))
        for group in (
            "input",
            "output",
            "data",
            "feature",
            "report",
            "log",
            "script",
            "analysis",
            "subflow",
            "checklist",
        )
    }


def test_log_projection_yosys_shape_has_no_foreign_keys(tmp_path):
    workspace = Workspace(directory=tmp_path, design=OriginDesign(name="gcd", top_module="gcd"))
    step = yosys_builder.build_step(workspace, "Synthesis", None, tmp_path / "in.v")
    keys = _shape_keys(step)
    assert keys["output"] == sorted(
        ["dir", "def", "verilog", "sim_verilog", "json", "report", "image"]
    )
    assert keys["data"] == sorted(["dir", "tmp"])
    assert keys["feature"] == sorted(["dir", "step", "generic_stat", "stat"])
    assert keys["report"] == sorted(["dir", "stat", "check"])
    assert keys["script"] == sorted(["dir", "main"])  # no sizer_env/sizer_cmd
    assert keys["analysis"] == sorted(
        ["dir", "metrics", "qor_metrics", "qor_summary", "qor_hotspots"]
    )
    # foreign ecc-only keys never appear on the synthesis shape
    for foreign in ("db", "gds", "lef", "lib", "spef", "view_json"):
        assert foreign not in keys["output"]


def test_log_projection_ecc_shape_has_no_sizer_keys(tmp_path):
    workspace = Workspace(directory=tmp_path, design=OriginDesign(name="gcd", top_module="gcd"))
    step = ecc_builder.build_step(workspace, "Floorplan", tmp_path / "i.def", tmp_path / "i.v")
    keys = _shape_keys(step)
    assert keys["output"] == sorted(
        [
            "dir",
            "def",
            "verilog",
            "json",
            "image",
            "db",
            "gds",
            "geometry",
            "geometry_manifest",
            "view_json",
            "view_json_edits",
            "lef",
            "lib",
            "spef",
        ]
    )
    assert keys["script"] == sorted(["dir", "main"])  # a normal ECC step is not sizer
    assert keys["report"] == sorted(["dir", "db", "step", "sta"])
    assert keys["analysis"] == sorted(
        [
            "dir",
            "metrics",
            "qor_metrics",
            "qor_summary",
            "qor_hotspots",
            "sta_timing_issues",
            "statis_csv",
        ]
    )


def test_log_projection_sizer_shape_includes_sizer_script_keys(tmp_path):
    from chipcompiler.tools.ecc_sizer import builder as sizer_builder

    workspace = Workspace(directory=tmp_path, design=OriginDesign(name="gcd", top_module="gcd"))
    step = sizer_builder.build_step(
        workspace, "Timing optimization", tmp_path / "i.def", tmp_path / "i.v"
    )
    keys = _shape_keys(step)
    # sizer is the only shape that populates sizer_env/sizer_cmd.
    assert keys["script"] == sorted(["dir", "main", "sizer_env", "sizer_cmd"])
    assert step.output.db == ""


class _CapturingLogger(Logger):
    """Logger subclass that records the rendered group tables from info(...)."""

    def __init__(self) -> None:
        super().__init__(name="test-capture")
        self.messages: list[str] = []

    def info(self, msg: str, *args, **kwargs) -> None:
        self.messages.append(msg % args if args else msg)


def test_log_workspace_step_renders_legacy_tables(tmp_path):
    # The whole facade path must still render key/value tables (not dataclass repr).
    workspace = Workspace(
        directory=tmp_path,
        design=OriginDesign(name="gcd", top_module="gcd"),
    )
    step = ecc_builder.build_step(workspace, "Floorplan", tmp_path / "i.def", tmp_path / "i.v")
    logger = _CapturingLogger()
    log_workspace_step(step, logger)
    rendered = "\n".join(logger.messages)
    # legacy key/value tables present; typed-dataclass repr absent.
    assert "def" in rendered
    assert "EccOutput(" not in rendered


def test_load_metrics_requires_present_metrics_path():
    from chipcompiler.analysis.step import StepMetricsBuilder

    builder = StepMetricsBuilder(workspace=Workspace())
    step = EccStep(name="place")  # analysis.metrics is None (never set)
    with pytest.raises(ValueError):
        builder.load(step)
