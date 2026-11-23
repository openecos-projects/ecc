"""Frozen full-SDC workspaces remain usable without accepting new full-SDC inputs."""

import json
import shutil
import subprocess
from copy import deepcopy

import pytest

from chipcompiler.data import create_workspace, load_workspace, refresh_workspace_config
from chipcompiler.data.workspace.sdc import signoff_sdc_path

FULL_SDC = """set period 7.5
create_clock -name CORE -period $period [get_ports clk]
set_input_delay 0.4 -clock CORE [get_ports data]
set_propagated_clock [all_clocks]
"""


@pytest.fixture
def workspace_args(tmp_path, minimal_ics55_pdk_factory, default_ics55_parameters, gcd_rtl_file):
    return dict(
        directory=tmp_path / "run",
        origin_def="",
        origin_verilog=gcd_rtl_file,
        pdk="ics55",
        pdk_root=minimal_ics55_pdk_factory(tmp_path / "pdk"),
        parameters=default_ics55_parameters,
    )


@pytest.fixture
def legacy_directory(workspace_args):
    workspace = create_workspace(**workspace_args)
    assert workspace is not None
    origin = workspace.directory / "origin"
    for path in origin.glob("*CTS/*.tcl"):
        path.unlink()
    # This is the persisted full-SDC layout emitted before the input migration:
    # the DB config points at the original, not a managed scenario or wrapper.
    source = origin / "legacy [clock] $input.sdc"
    source.write_text(FULL_SDC)
    db_path = workspace.config["db"]
    db = json.loads(db_path.read_text())
    db["INPUT"]["sdc_path"] = str(source)
    db_path.write_text(json.dumps(db))
    return workspace.directory


@pytest.mark.parametrize("read_only", [False, True])
@pytest.mark.parametrize("copied", [False, True])
def test_reopen_refresh_and_select_legacy_sdc(legacy_directory, tmp_path, read_only, copied):
    directory = legacy_directory
    if copied:
        directory = tmp_path / "copied"
        shutil.copytree(legacy_directory, directory)
    source = next((directory / "origin").glob("*.sdc"))
    original = (source.read_bytes(), source.stat().st_mtime_ns)
    workspace = load_workspace(directory, read_only=read_only)
    assert workspace.pdk.sdc == source
    parameters = deepcopy(workspace.parameters.data)

    refresh_workspace_config(workspace)

    assert workspace.parameters.data == parameters
    assert workspace.pdk.sdc == source
    assert load_workspace(directory).pdk.sdc == source
    for post_cts, phase, command in (
        (False, "pre_CTS", "remove_propagated_clock"),
        (True, "post_CTS", "set_propagated_clock"),
    ):
        path = signoff_sdc_path(
            workspace, directory / "unused.tcl", post_cts=post_cts, corner="MIN", rc_para="Cbest"
        )
        assert path == directory / "origin" / phase / f"{source.name}.ecc.tcl"
        text = path.read_text()
        assert text.endswith(f"{command} [all_clocks]\n")
        assert "set_timing_derate" not in text
        _execute_wrapper(text, propagated=post_cts)
    assert (source.read_bytes(), source.stat().st_mtime_ns) == original
    if copied:
        assert list((legacy_directory / "origin").glob("*CTS/*.tcl")) == []


def _execute_wrapper(text, *, propagated):
    interpreter = shutil.which("tclsh")
    if interpreter is None:
        pytest.skip("Tcl interpreter not installed")
    harness = """proc get_ports {name} {return $name}
proc all_clocks {} {return CORE}
proc create_clock {args} {puts [list create_clock {*}$args]}
proc set_input_delay {args} {puts [list set_input_delay {*}$args]}
proc set_propagated_clock {args} {set ::propagated 1}
proc remove_propagated_clock {args} {set ::propagated 0}
"""
    result = subprocess.run(
        [interpreter],
        input=harness + text + 'puts "propagated=$propagated"\n',
        text=True,
        capture_output=True,
        check=True,
    )
    assert result.stderr == ""
    assert result.stdout.splitlines() == [
        "create_clock -name CORE -period 7.5 clk",
        "set_input_delay 0.4 -clock CORE data",
        f"propagated={int(propagated)}",
    ]


def test_new_workspace_still_rejects_full_sdc(workspace_args, tmp_path):
    source = tmp_path / "new.sdc"
    source.write_text(FULL_SDC)
    with pytest.raises(ValueError, match="not a full SDC/Tcl script"):
        create_workspace(**workspace_args, sdc=source)
    assert source.read_text() == FULL_SDC
