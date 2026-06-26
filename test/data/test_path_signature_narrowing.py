import inspect
from pathlib import Path
from typing import get_type_hints

import chipcompiler.data.workspace as workspace_module
from chipcompiler.tools import eda
from chipcompiler.tools.ecc import builder as ecc_builder
from chipcompiler.tools.ecc_dreamplace import builder as dreamplace_builder
from chipcompiler.tools.ecc_sizer import builder as sizer_builder
from chipcompiler.tools.yosys import builder as yosys_builder
from chipcompiler.data.checklist import Checklist
from chipcompiler.data.home import HomeData, _read_normalized_home_data
from chipcompiler.data.parameter import get_design_parameters, get_parameters, load_parameter
from chipcompiler.utility.json import json_read, json_write


def _parameter_annotation(function, name: str):
    return inspect.signature(function).parameters[name].annotation


def _parameter_default(function, name: str):
    return inspect.signature(function).parameters[name].default


def _hint(function, name: str):
    return get_type_hints(function)[name]


def test_json_helpers_require_path_inputs():
    assert _parameter_annotation(json_read, "file_path") is Path
    assert _parameter_annotation(json_write, "file_path") is Path


def test_parameter_loaders_use_path_or_none():
    assert _parameter_annotation(load_parameter, "path") is Path
    assert _parameter_annotation(get_parameters, "path") == Path | None
    assert _parameter_default(get_parameters, "path") is None
    assert _parameter_annotation(get_design_parameters, "path") == Path | None
    assert _parameter_default(get_design_parameters, "path") is None


def test_home_data_path_api_uses_path_or_none():
    assert _parameter_annotation(_read_normalized_home_data, "path") is Path
    assert _parameter_annotation(HomeData.__init__, "path") == Path | None
    assert _parameter_default(HomeData.__init__, "path") is None
    assert _parameter_annotation(HomeData.init, "path") is Path
    assert _parameter_annotation(HomeData._set_path_value, "path") is Path
    assert _parameter_annotation(HomeData.set_parameters, "path") is Path
    assert _parameter_annotation(HomeData.set_flow, "path") is Path
    assert _parameter_annotation(HomeData.set_layout, "path") is Path
    assert _parameter_annotation(HomeData.set_gds_merge, "path") is Path
    assert _parameter_annotation(HomeData._set_metric, "image_path") is Path
    assert _parameter_annotation(HomeData.set_metrics_inst_dist, "image_path") is Path
    assert _parameter_annotation(HomeData.set_metrics_layer_via_dist, "image_path") is Path
    assert _parameter_annotation(HomeData.set_metrics_layer_wire_dist, "image_path") is Path
    assert _parameter_annotation(HomeData.set_metrics_pin_dist, "image_path") is Path
    assert _parameter_annotation(HomeData.set_metrics_drc_dist, "image_path") is Path
    assert _parameter_annotation(HomeData.set_metrics_cts_skew_map, "image_path") is Path
    assert _parameter_annotation(HomeData.set_checklist, "checklist_path") is Path


def test_checklist_requires_path_input():
    assert _parameter_annotation(Checklist.__init__, "path") is Path


def test_workspace_internal_path_helpers_use_path_inputs():
    assert _hint(workspace_module._mapping_config_path, "return") == Path | None
    assert _hint(workspace_module.sync_workspace_config_to_parameters, "config_path") is Path
    assert _hint(workspace_module._path_is_within, "path") is Path
    assert _hint(workspace_module._path_is_within, "directory") is Path


def test_tool_dispatcher_passes_path_or_none_to_builders():
    assert _hint(eda.create_step, "input_def") == Path | None
    assert _hint(eda.create_step, "input_verilog") == Path | None
    assert _hint(eda.create_step, "input_db") == Path | None
    assert _hint(eda.create_step, "output_def") == Path | None
    assert _hint(eda.create_step, "output_verilog") == Path | None
    assert _hint(eda.create_step, "output_gds") == Path | None


def test_ecc_builder_path_inputs_are_path_or_none():
    assert _hint(ecc_builder.build_step, "input_def") == Path | None
    assert _hint(ecc_builder.build_step, "input_verilog") == Path | None
    assert _hint(ecc_builder.build_step, "input_db") == Path | None
    assert _hint(ecc_builder.build_step, "output_def") == Path | None
    assert _hint(ecc_builder.build_step, "output_verilog") == Path | None
    assert _hint(ecc_builder.build_step, "output_gds") == Path | None
    assert _hint(ecc_builder.build_step, "step_directory") == Path | None


def test_yosys_builder_path_inputs_are_path_only():
    assert _hint(yosys_builder._abspath, "path") == Path | None
    assert _hint(yosys_builder._existing_unique_paths, "paths") == list[Path]
    assert _hint(yosys_builder.build_step, "input_def") == Path | None
    assert _hint(yosys_builder.build_step, "input_verilog") == Path | None
    assert _hint(yosys_builder.build_step, "input_db") == Path | None
    assert _hint(yosys_builder.build_step, "output_def") == Path | None
    assert _hint(yosys_builder.build_step, "output_verilog") == Path | None
    assert _hint(yosys_builder.build_step, "output_gds") == Path | None


def test_sizer_builder_path_inputs_are_path_only():
    assert _hint(sizer_builder.build_step, "input_def") == Path | None
    assert _hint(sizer_builder.build_step, "input_verilog") == Path | None
    assert _hint(sizer_builder.build_step, "input_db") == Path | None
    assert _hint(sizer_builder.build_step, "output_def") == Path | None
    assert _hint(sizer_builder.build_step, "output_verilog") == Path | None
    assert _hint(sizer_builder.build_step, "output_gds") == Path | None
    assert _hint(sizer_builder._copy_or_seed_template, "template") == Path | None
    assert _hint(sizer_builder._copy_or_seed_template, "target") is Path
    assert _hint(sizer_builder._append_text, "path") is Path


def test_dreamplace_builder_path_inputs_are_path_or_none():
    assert _hint(dreamplace_builder.build_step, "input_def") == Path | None
    assert _hint(dreamplace_builder.build_step, "input_verilog") == Path | None
    assert _hint(dreamplace_builder.build_step, "input_db") == Path | None
    assert _hint(dreamplace_builder.build_step, "output_def") == Path | None
    assert _hint(dreamplace_builder.build_step, "output_verilog") == Path | None
    assert _hint(dreamplace_builder.build_step, "output_gds") == Path | None
