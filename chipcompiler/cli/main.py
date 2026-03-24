#!/usr/bin/env python

import argparse
import os
import sys
from collections.abc import Sequence

from chipcompiler.data import create_workspace, get_parameters
from chipcompiler.engine import EngineFlow
from chipcompiler.rtl2gds import build_rtl2gds_flow
from chipcompiler.utility.filelist import parse_filelist, validate_filelist

FILELIST_SUFFIXES = {".f", ".fl", ".filelist"}
RTL_SUFFIXES = {".v", ".sv", ".svh", ".vh"}


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="cli",
        description="Create ChipCompiler workspace and run RTL2GDS flow",
    )
    parser.add_argument("--workspace", required=True, help="Workspace directory path")
    parser.add_argument("--rtl", required=True, help="RTL file or filelist path")
    parser.add_argument("--design", required=True, help="Design name")
    parser.add_argument("--top", required=True, help="Top module name")
    parser.add_argument("--clock", required=True, help="Clock port name")
    parser.add_argument("--pdk-root", required=True, help="ICS55 PDK root directory")
    parser.add_argument(
        "--freq",
        type=float,
        default=100.0,
        help="Clock frequency in MHz (default: 100)",
    )
    return parser


def resolve_rtl_input(rtl_path: str) -> tuple[str, str, str]:
    normalized_path = os.path.abspath(os.path.expanduser(rtl_path))
    suffix = os.path.splitext(normalized_path)[1].lower()

    if suffix in FILELIST_SUFFIXES:
        return ("filelist", "", normalized_path)

    if suffix in RTL_SUFFIXES:
        return ("rtl", normalized_path, "")

    try:
        parse_filelist(normalized_path)
        _, missing_files = validate_filelist(normalized_path)
        if len(missing_files) == 0:
            return ("filelist", "", normalized_path)
    except Exception:
        pass

    return ("rtl", normalized_path, "")


def build_parameters(args: argparse.Namespace) -> dict:
    parameters = get_parameters("ics55")
    parameters.data.update(
        {
            "PDK": "ics55",
            "Design": args.design,
            "Top module": args.top,
            "Clock": args.clock,
            "Frequency max [MHz]": args.freq,
        }
    )
    return parameters.data


def _validate_args(args: argparse.Namespace) -> str | None:
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


def run(argv: Sequence[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(list(argv) if argv is not None else None)

    validation_error = _validate_args(args)
    if validation_error:
        print(f"Error: {validation_error}", file=sys.stderr)
        return 1

    try:
        _, origin_verilog, input_filelist = resolve_rtl_input(args.rtl)
        parameters = build_parameters(args)

        workspace = create_workspace(
            directory=args.workspace,
            origin_def="",
            origin_verilog=origin_verilog,
            pdk="ics55",
            parameters=parameters,
            input_filelist=input_filelist,
            pdk_root=args.pdk_root,
        )
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
    except Exception as exc:
        print(f"Error: {exc}", file=sys.stderr)
        return 1


def main() -> None:
    sys.exit(run())


if __name__ == "__main__":
    main()
