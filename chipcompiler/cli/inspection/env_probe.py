"""Host environment probes for `ecc doctor` and `ecc run` preflight.

Each probe returns a :class:`ProbeResult` describing one component's
availability. Probes never raise and never mutate process state; diagnostics
they trigger (tool logs, PDK validation errors) go to stderr so stdout stays
reserved for command records.
"""

import contextlib
import dataclasses
import sys
import tempfile

PASS = "pass"
FAIL = "fail"
SKIP = "skip"


@dataclasses.dataclass(frozen=True)
class ProbeResult:
    component: str
    status: str
    required: bool = True
    detail: str = ""
    remediation: str = ""


def probe_yosys() -> ProbeResult:
    from chipcompiler.tools.yosys.utility import get_yosys_command, get_yosys_not_found_error

    command = get_yosys_command()
    if command:
        return ProbeResult("yosys", PASS, detail=" ".join(command))
    return ProbeResult("yosys", FAIL, remediation=get_yosys_not_found_error())


def probe_yosys_slang() -> ProbeResult:
    """Doctor-only probe: spawn yosys and check the slang frontend."""
    from chipcompiler.tools.yosys.utility import (
        check_slang_support,
        get_yosys_command,
        get_yosys_runtime,
    )

    if not get_yosys_command():
        return ProbeResult("yosys-slang", SKIP, detail="yosys not installed")
    yosys_cmd, yosys_env = get_yosys_runtime()
    with (
        tempfile.TemporaryDirectory() as probe_dir,
        tempfile.TemporaryFile("w+") as log_file,
        contextlib.redirect_stdout(sys.stderr),
    ):
        supported = check_slang_support(yosys_cmd, probe_dir, yosys_env, log_file)
    if supported:
        return ProbeResult("yosys-slang", PASS, detail="read_slang frontend available")
    return ProbeResult(
        "yosys-slang",
        FAIL,
        remediation=(
            "Use a yosys build with slang support (builtin since v0.67, or a loadable "
            "slang plugin), e.g. the latest OSS CAD Suite."
        ),
    )


def probe_ecc_tools() -> ProbeResult:
    from chipcompiler.cli.core.version_info import distribution_version
    from chipcompiler.tools.ecc.utility import is_eda_exist

    version = distribution_version("ecc-tools-bin")
    if is_eda_exist():
        return ProbeResult("ecc-tools", PASS, detail=f"ecc-tools-bin {version}")
    return ProbeResult(
        "ecc-tools",
        FAIL,
        remediation="Reinstall the ecc CLI bundle; the bundled ecc-tools-bin package is missing.",
    )


def probe_dreamplace() -> ProbeResult:
    from chipcompiler.cli.core.version_info import distribution_version
    from chipcompiler.tools.ecc_dreamplace.utility import is_eda_exist

    version = distribution_version("ecc-dreamplace")
    with contextlib.redirect_stdout(sys.stderr):
        available = is_eda_exist()
    if available:
        return ProbeResult("dreamplace", PASS, detail=f"ecc-dreamplace {version}")
    return ProbeResult(
        "dreamplace",
        FAIL,
        remediation="Reinstall the ecc CLI bundle; the bundled ecc-dreamplace package is missing.",
    )


def probe_klayout() -> ProbeResult:
    from chipcompiler.tools.klayout_tool.utility import is_eda_exist

    if is_eda_exist():
        return ProbeResult("klayout", PASS, required=False, detail="klayout module available")
    return ProbeResult(
        "klayout",
        FAIL,
        required=False,
        detail="optional; used only by layout-image rendering",
        remediation="pip install klayout",
    )


def probe_sizer() -> ProbeResult:
    from chipcompiler.tools.ecc_sizer.utility import (
        get_sizer_command,
        is_eda_exist,
        is_sizer_runtime_exist,
    )

    if is_eda_exist() and is_sizer_runtime_exist():
        return ProbeResult("sizer", PASS, detail=" ".join(get_sizer_command()))
    return ProbeResult(
        "sizer",
        FAIL,
        detail="required by timing optimization steps",
        remediation=(
            "Build ecc-sizer, add its build/src directory to PATH, and set "
            "CHIPCOMPILER_ECC_SIZER_ROOT to the checkout."
        ),
    )


def probe_pdk(cfg) -> ProbeResult:
    if cfg is None:
        return ProbeResult(
            "pdk",
            SKIP,
            detail="no ecc.toml found; run inside a project or pass --project",
        )
    from chipcompiler.cli.project.config import (
        _validate_pdk_contents,
        resolve_pdk_overrides,
        resolve_pdk_root,
    )

    root = resolve_pdk_root(cfg)
    if not root:
        return ProbeResult(
            "pdk",
            FAIL,
            detail=f"pdk.name={cfg.pdk_name}",
            remediation=(
                "Set pdk.root in ecc.toml, or export CHIPCOMPILER_ICS55_PDK_ROOT / "
                "ICS55_PDK_ROOT pointing at the icsprout55-pdk checkout."
            ),
        )
    with contextlib.redirect_stdout(sys.stderr):
        problem = _validate_pdk_contents(cfg.pdk_name, root, resolve_pdk_overrides(cfg))
    if problem is None:
        return ProbeResult("pdk", PASS, detail=root)
    return ProbeResult("pdk", FAIL, detail=root, remediation=problem)


_PROBES = {
    "yosys": probe_yosys,
    "yosys-slang": probe_yosys_slang,
    "ecc-tools": probe_ecc_tools,
    "dreamplace": probe_dreamplace,
    "klayout": probe_klayout,
    "sizer": probe_sizer,
}

ALL_COMPONENTS = (*_PROBES, "pdk")


def probe_environment(components, *, cfg=None, include_slang=True) -> list[ProbeResult]:
    """Run the requested probes in order and return their results.

    A probe that raises is reported as a failure instead of aborting the
    sweep: doctor's job is to describe the environment, not to crash on it.
    """
    results = []
    for component in components:
        if component == "yosys-slang" and not include_slang:
            continue
        try:
            if component == "pdk":
                results.append(probe_pdk(cfg))
            else:
                results.append(_PROBES[component]())
        except Exception as exc:  # noqa: BLE001 -- probes must not crash doctor
            results.append(ProbeResult(component, FAIL, remediation=f"probe failed: {exc}"))
    return results


def probe_components_for_preset(preset: str) -> tuple[str, ...]:
    """Components a flow preset needs at minimum before it can start.

    The PDK is not probed here: `ecc run` already validates it through
    validate_project_config, and the slang check is left to the synthesis
    step's existing fail-fast so preflight stays fast.
    """
    from chipcompiler import rtl2gds as rtl2gds_api

    tools = {tool for _step, tool, _state in rtl2gds_api.get_flow_builders()[preset]()}
    components = ["ecc-tools"]
    if "yosys" in tools:
        components.append("yosys")
    if "dreamplace" in tools:
        components.append("dreamplace")
    if "sizer" in tools:
        components.append("sizer")
    return tuple(components)
