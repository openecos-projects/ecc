#!/usr/bin/env python

"""Contract tests for the PathLike pass-through migration of the ecc wrapper.

The native ecc_py bindings accept str | os.PathLike | None (None only where
the binding parameter is optional), so the wrapper passes path arguments
through unchanged. The only remaining normalization is the two string-typed
config_dict values.
"""

import subprocess
import sys
from pathlib import Path

from chipcompiler.tools.ecc.module import ECCToolsModule

from .test_module import FakeEcc

MODULE_PATH = Path(__file__).resolve().parents[3] / "chipcompiler" / "tools" / "ecc" / "module.py"


def test_module_source_keeps_path_text_only_for_config_dict_values():
    source = MODULE_PATH.read_text(encoding="utf-8")

    assert "path_texts" not in source

    path_text_lines = [line for line in source.splitlines() if "path_text(" in line]
    assert len(path_text_lines) == 2
    for line in path_text_lines:
        assert '"-temp_directory_path"' in line


def test_real_binding_doc_renders_pathlike_contract():
    ecc = ECCToolsModule().get_ecc()

    assert "sdc_path: Optional[os.PathLike] = None" in ecc.sdc_init.__doc__
    init_rt_doc = ecc.init_rt.__doc__
    assert "config: Optional[os.PathLike] = None" in init_rt_doc
    assert "config_dict: Dict[str, str]" in init_rt_doc
    assert "def_path: os.PathLike" in ecc.def_init.__doc__
    assert "lef_paths: List[os.PathLike]" in ecc.lef_init.__doc__
    verilog_init_doc = ecc.verilog_init.__doc__
    assert "verilog_path: os.PathLike" in verilog_init_doc
    assert "top_module: str" in verilog_init_doc


def _probe_binding(code: str) -> str:
    """Run a live ecc_py call in a fresh subprocess.

    ecc_py holds global singleton state, so every live behavior probe gets
    its own interpreter to keep the equivalence assertions independent.
    """
    result = subprocess.run(
        [sys.executable, "-c", code],
        capture_output=True,
        text=True,
        check=True,
    )
    for line in reversed(result.stdout.splitlines()):
        if line.startswith("RESULT="):
            return line.removeprefix("RESULT=")
    raise AssertionError(f"probe produced no RESULT line: {result.stdout!r}")


def test_real_binding_sdc_init_none_matches_empty_string():
    none_result = _probe_binding(
        "from ecc_tools_bin import ecc_py; print('RESULT=%s' % ecc_py.sdc_init(None))"
    )
    empty_result = _probe_binding(
        "from ecc_tools_bin import ecc_py; print('RESULT=%s' % ecc_py.sdc_init(''))"
    )

    assert none_result == "True"
    assert empty_result == "True"


def test_real_binding_def_init_path_matches_str_for_missing_file():
    path_result = _probe_binding(
        "from pathlib import Path; from ecc_tools_bin import ecc_py;"
        " print('RESULT=%s' % ecc_py.def_init(Path('/nonexistent.def')))"
    )
    str_result = _probe_binding(
        "from ecc_tools_bin import ecc_py; print('RESULT=%s' % ecc_py.def_init('/nonexistent.def'))"
    )

    assert path_result == "False"
    assert str_result == "False"


def test_real_binding_init_rt_none_config_matches_empty_string():
    none_result = _probe_binding(
        "from ecc_tools_bin import ecc_py;"
        " print('RESULT=%s' % ecc_py.init_rt(config=None, config_dict={}))"
    )
    empty_result = _probe_binding(
        "from ecc_tools_bin import ecc_py;"
        " print('RESULT=%s' % ecc_py.init_rt(config='', config_dict={}))"
    )

    assert none_result == empty_result == "False"


def test_write_timing_model_passes_none_sdc_to_binding(tmp_path):
    module = ECCToolsModule.__new__(ECCToolsModule)
    module.ecc = FakeEcc()
    timing_output = tmp_path / "output" / "gcd.lib"

    module.write_timing_model(
        timing_output,
        config="",
        output_dir=tmp_path / "sta",
        lib_paths=[],
        sdc_path=None,
        spef_path="",
        design_name="gcd",
    )

    assert ("sdc_init", (None,), {}) in module.ecc.calls
    assert ("sdc_init", ("",), {}) not in module.ecc.calls
    assert timing_output.read_text(encoding="utf-8") == module.ecc.generated_timing_lib_contents
