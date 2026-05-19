import argparse
import os
import sys

_LEGACY_FLAGS = {"--workspace", "--rtl", "--design", "--top", "--clock", "--pdk-root", "--freq"}


def is_legacy_workspace_args(args: list[str]) -> bool:
    if args and args[0] == "workspace":
        return False
    for arg in args:
        if arg in _LEGACY_FLAGS:
            return True
        if "=" in arg and arg.split("=", 1)[0] in _LEGACY_FLAGS:
            return True
    return False


def _resolve_rtl_input(rtl_path: str) -> tuple[str, str]:
    from chipcompiler.utility.filelist import parse_filelist, validate_filelist

    normalized = os.path.abspath(os.path.expanduser(rtl_path))
    suffix = os.path.splitext(normalized)[1].lower()
    if suffix in {".f", ".fl", ".filelist"}:
        return ("", normalized)
    if suffix in {".v", ".sv", ".svh", ".vh"}:
        return (normalized, "")
    try:
        parse_filelist(normalized)
        _, missing = validate_filelist(normalized)
        if not missing:
            return ("", normalized)
    except Exception:
        pass
    return (normalized, "")


def _validate_legacy_args(args) -> str | None:
    if not str(args.workspace).strip():
        return "--workspace must not be empty"
    if not str(args.design).strip():
        return "--design must not be empty"
    if not str(args.top).strip():
        return "--top must not be empty"
    if not str(args.clock).strip():
        return "--clock must not be empty"
    rtl_path = os.path.abspath(os.path.expanduser(args.rtl))
    if not os.path.exists(rtl_path):
        return f"--rtl path does not exist: {rtl_path}"
    if not os.path.isfile(rtl_path):
        return f"--rtl must point to a file: {rtl_path}"
    pdk_root = os.path.abspath(os.path.expanduser(args.pdk_root))
    if not os.path.exists(pdk_root):
        return f"--pdk-root path does not exist: {pdk_root}"
    if not os.path.isdir(pdk_root):
        return f"--pdk-root must point to a directory: {pdk_root}"
    if args.freq <= 0:
        return "--freq must be greater than 0"
    return None


def run_legacy_workspace(argv: list[str]) -> int:
    from chipcompiler.data import create_workspace, get_parameters
    from chipcompiler.engine import EngineFlow
    from chipcompiler.rtl2gds import build_rtl2gds_flow

    parser = argparse.ArgumentParser(
        prog="cli",
        description="Legacy parameter-only invocation (use 'ecc run' for project-based flows)",
    )
    parser.add_argument("--workspace", required=True)
    parser.add_argument("--rtl", required=True)
    parser.add_argument("--design", required=True)
    parser.add_argument("--top", required=True)
    parser.add_argument("--clock", required=True)
    parser.add_argument("--pdk-root", required=True)
    parser.add_argument("--freq", type=float, default=100.0)
    try:
        args = parser.parse_args(argv)
    except SystemExit as exc:
        return int(exc.code or 0)

    err = _validate_legacy_args(args)
    if err:
        print(f"Error: {err}", file=sys.stderr)
        return 1

    parameters = get_parameters("ics55")
    parameters.data.update({
        "PDK": "ics55",
        "Design": args.design,
        "Top module": args.top,
        "Clock": args.clock,
        "Frequency max [MHz]": args.freq,
    })

    origin_verilog, input_filelist = _resolve_rtl_input(args.rtl)

    try:
        workspace = create_workspace(
            directory=args.workspace,
            origin_def="",
            origin_verilog=origin_verilog,
            pdk="ics55",
            parameters=parameters,
            input_filelist=input_filelist,
            pdk_root=args.pdk_root,
        )
    except Exception as exc:
        print(f"Error: {exc}", file=sys.stderr)
        return 1

    if workspace is None:
        print("Error: failed to create workspace", file=sys.stderr)
        return 1

    engine_flow = EngineFlow(workspace=workspace)
    if not engine_flow.has_init():
        for step, tool, state in build_rtl2gds_flow():
            engine_flow.add_step(step=step, tool=tool, state=state)

    engine_flow.create_step_workspaces()

    if not engine_flow.run_steps():
        print("Error: flow execution failed", file=sys.stderr)
        return 1

    return 0
