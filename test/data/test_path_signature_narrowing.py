import inspect
from pathlib import Path

from chipcompiler.data.checklist import Checklist
from chipcompiler.data.home import HomeData, _read_normalized_home_data
from chipcompiler.data.parameter import get_design_parameters, get_parameters, load_parameter
from chipcompiler.utility.json import json_read, json_write


def _parameter_annotation(function, name: str):
    return inspect.signature(function).parameters[name].annotation


def _parameter_default(function, name: str):
    return inspect.signature(function).parameters[name].default


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
