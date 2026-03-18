#!/usr/bin/env python
# -*- encoding: utf-8 -*-

from __future__ import annotations

import importlib.machinery
import json
import logging
import os
import sys
from pathlib import Path

from chipcompiler.data import StepEnum, Workspace, WorkspaceStep

from .module import ECCToolsModule


LOGGER = logging.getLogger(__name__)


def _dreamplace_install_root() -> Path:
    return Path(__file__).resolve().parent / "dreamplace"


def _dreamplace_package_root() -> Path:
    return _dreamplace_install_root() / "dreamplace"


def _ensure_import_path() -> None:
    root = str(_dreamplace_install_root())
    if root not in sys.path:
        sys.path.insert(0, root)


def _compiled_extension_abi_tags() -> list[str]:
    abi_tags: set[str] = set()
    for extension_path in _dreamplace_package_root().rglob("*.so"):
        if ".cpython-" not in extension_path.name:
            continue
        abi_tag = extension_path.name.split(".cpython-", 1)[1].split("-", 1)[0]
        abi_tags.add(abi_tag)
    return sorted(abi_tags)


def _current_extension_abi_tag() -> str | None:
    for suffix in importlib.machinery.EXTENSION_SUFFIXES:
        if not suffix.startswith(".cpython-"):
            continue
        return suffix.split(".cpython-", 1)[1].split("-", 1)[0]
    return None


def _rebuild_hint() -> str:
    return (
        "Rebuild and reinstall DreamPlace with "
        f"`-DPYTHON_EXECUTABLE={sys.executable}` so the compiled extensions match "
        "the active interpreter."
    )


def _module_paths(module_name: str) -> tuple[Path, Path]:
    module_parts = module_name.split(".")
    relative_parts = module_parts[1:]
    module_path = _dreamplace_package_root().joinpath(*relative_parts)
    return module_path, module_path.with_suffix(".py")


def _compiled_module_paths(module_name: str) -> list[Path]:
    module_path, _ = _module_paths(module_name)
    return sorted(module_path.parent.glob(f"{module_path.name}*.so"))


def _python_module_exists(module_name: str) -> bool:
    module_path, module_file = _module_paths(module_name)
    return module_path.is_dir() or module_file.exists()


def _current_torch_cxx11_abi() -> int | None:
    try:
        import torch
    except Exception:
        return None

    abi_flag = getattr(getattr(torch, "_C", object()), "_GLIBCXX_USE_CXX11_ABI", None)
    if abi_flag is None:
        return None
    return int(bool(abi_flag))


def _cxx_abi_rebuild_hint() -> str:
    torch_abi = _current_torch_cxx11_abi()
    if torch_abi is None:
        return _rebuild_hint()
    return (
        "Rebuild and reinstall DreamPlace with "
        f"`-DPYTHON_EXECUTABLE={sys.executable}` and "
        f"`-DCMAKE_CXX_ABI={torch_abi}` so the compiled extensions match the active "
        "PyTorch runtime."
    )


def _load_dreamplace():
    _ensure_import_path()

    try:
        from dreamplace.Params import Params
        from dreamplace.Placer import PlacementEngine
    except ModuleNotFoundError as exc:
        if exc.name and exc.name.startswith("dreamplace.ops."):
            compiled_module_paths = _compiled_module_paths(exc.name)
            if compiled_module_paths:
                abi_tags = sorted(
                    {
                        path.name.split(".cpython-", 1)[1].split("-", 1)[0]
                        for path in compiled_module_paths
                        if ".cpython-" in path.name
                    }
                )
                current_abi_tag = _current_extension_abi_tag()
                raise ModuleNotFoundError(
                    f"{exc}. DreamPlace extensions under '{_dreamplace_package_root()}' "
                    f"were built for CPython ABI tag(s) {abi_tags}, but the current "
                    f"interpreter expects '{current_abi_tag or 'unknown'}'. "
                    f"{_rebuild_hint()}"
                ) from exc
            if not _python_module_exists(exc.name):
                raise ModuleNotFoundError(
                    f"{exc}. DreamPlace module '{exc.name}' was not installed under "
                    f"'{_dreamplace_package_root()}'. Reinstall DreamPlace or update "
                    "the install rules so the missing module is copied into the runtime package."
                ) from exc
            raise ModuleNotFoundError(
                f"{exc}. DreamPlace could not resolve the required module from "
                f"'{_dreamplace_package_root()}'."
            ) from exc
        raise
    except ImportError as exc:
        message = str(exc)
        if "torchCheckFail" in message:
            torch_abi = _current_torch_cxx11_abi()
            raise ImportError(
                f"{exc}. DreamPlace extensions under '{_dreamplace_package_root()}' "
                "appear to be built with a different value of "
                "`_GLIBCXX_USE_CXX11_ABI` than the active PyTorch runtime. "
                f"Current torch expects '{torch_abi if torch_abi is not None else 'unknown'}'. "
                f"{_cxx_abi_rebuild_hint()}"
            ) from exc
        raise

    return Params, PlacementEngine


def is_dreamplace_available() -> bool:
    try:
        _load_dreamplace()
    except Exception as exc:
        LOGGER.debug("dreamplace import failed: %s", exc, exc_info=True)
        return False
    return True


class _LogContext:
    def __init__(self, log_path: str):
        self.log_path = log_path
        self.logger = logging.getLogger()
        self.original_handlers = []
        self.original_level = logging.INFO
        self.file_handler = None

    def __enter__(self):
        os.makedirs(os.path.dirname(self.log_path), exist_ok=True)
        self.original_handlers = list(self.logger.handlers)
        self.original_level = self.logger.level
        for handler in list(self.logger.handlers):
            self.logger.removeHandler(handler)
        self.file_handler = logging.FileHandler(self.log_path, mode="w")
        self.file_handler.setFormatter(
            logging.Formatter("[%(levelname)-7s] %(name)s - %(message)s")
        )
        self.logger.addHandler(self.file_handler)
        self.logger.setLevel(logging.INFO)
        return self

    def __exit__(self, exc_type, exc, tb):
        if self.file_handler is not None:
            self.logger.removeHandler(self.file_handler)
            self.file_handler.close()
        for handler in self.original_handlers:
            self.logger.addHandler(handler)
        self.logger.setLevel(self.original_level)
        return False


class EccStaAdapter:
    def __init__(self, module: ECCToolsModule):
        self.module = module

    def init_sta(self):
        return None

    def build_rc_tree_from_flat_data(self, *args, **kwargs):
        raise NotImplementedError("ecc dreamplace STA bridge is not implemented in this runtime")

    def update_and_get_all_pin_timings(self, *args, **kwargs):
        raise NotImplementedError("ecc dreamplace STA bridge is not implemented in this runtime")


class EccDbAdapter:
    def __init__(
        self,
        dir_workspace: str,
        module: ECCToolsModule,
        input_def: str = "",
        input_verilog: str = "",
        output_def: str = "",
        output_verilog: str = "",
    ):
        self.dir_workspace = dir_workspace
        self.module = module
        self.input_def = input_def
        self.input_verilog = input_verilog
        self.output_def = output_def
        self.output_verilog = output_verilog
        self._sta_adapter = None

    def read_def(self, path: str = ""):
        self.module.read_def(path or self.input_def)

    def def_save(self, def_path: str):
        self.module.def_save(def_path)

    def tcl_save(self, output_path: str):
        self.module.tcl_save(output_path)

    def get_dmInst_ptr(self):
        return self.module.get_dmInst_ptr()

    def pydb(
        self,
        dm_inst_ptr,
        route_num_bins_x: int,
        route_num_bins_y: int,
        routability_opt_flag: int,
        with_sta: int,
    ):
        return self.module.pydb(
            dm_inst_ptr,
            route_num_bins_x,
            route_num_bins_y,
            routability_opt_flag,
            with_sta,
        )

    def write_placement_back(self, dm_inst_ptr, node_x, node_y):
        self.module.write_placement_back(dm_inst_ptr, node_x, node_y)

    def build_macro_connection_map(self, max_hop: int):
        return self.module.build_macro_connection_map(max_hop)

    def get_sta_adapter(self):
        if self._sta_adapter is None:
            self._sta_adapter = EccStaAdapter(self.module)
        return self._sta_adapter


class DreamPlace:
    def __init__(
        self,
        workspace: Workspace,
        step: WorkspaceStep,
        module: ECCToolsModule,
        input_def: str,
        input_verilog: str,
        output_def: str,
        output_verilog: str,
    ):
        self.workspace = workspace
        self.step = step
        self.module = module
        self.input_def = input_def
        self.input_verilog = input_verilog
        self.output_def = output_def
        self.output_verilog = output_verilog
        self.param_path = step.config["dreamplace"]
        self.result_dir = step.data.get(step.name, step.data["dir"])

    def _build_params(self, params_cls, legalize_only: bool):
        with open(self.param_path, encoding="utf-8") as f_reader:
            config = json.load(f_reader)

        params = params_cls()
        params.fromJson(config)
        params.def_input = self.input_def
        params.verilog_input = self.input_verilog
        params.result_dir = self.result_dir
        params.base_design_name = self.workspace.design.name
        params.with_sta = False
        params.timing_opt_flag = 0
        params.timing_eval_flag = 0
        params.differentiable_timing_obj = 0

        if legalize_only:
            params.global_place_flag = 0
            params.legalize_flag = 1
            params.enable_fillers = 0
            params.random_center_init_flag = 0
            params.auto_adjust_bins = 1

        return params

    def _log_path(self, legalize_only: bool) -> str:
        log_name = "dreamplace_legalization.log" if legalize_only else "dreamplace_placement.log"
        return os.path.join(self.result_dir, log_name)

    def _run(self, legalize_only: bool) -> bool:
        Params, PlacementEngine = _load_dreamplace()
        params = self._build_params(Params, legalize_only=legalize_only)
        data_manager = EccDbAdapter(
            dir_workspace=self.step.directory,
            module=self.module,
            input_def=self.input_def,
            input_verilog=self.input_verilog,
            output_def=self.output_def,
            output_verilog=self.output_verilog,
        )

        with _LogContext(self._log_path(legalize_only)):
            engine = PlacementEngine(params)
            engine.setup_rawdb(data_manager=data_manager)
            ppa = engine.run()

        if ppa.get("hpwl") == float("inf"):
            LOGGER.error("dreamplace failed for %s", self.step.name)
            return False

        return True

    def run_placement(self) -> bool:
        return self._run(legalize_only=False)

    def run_legalization(self) -> bool:
        if self.step.name != StepEnum.LEGALIZATION.value:
            return False
        return self._run(legalize_only=True)
