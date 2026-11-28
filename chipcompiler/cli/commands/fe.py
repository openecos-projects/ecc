"""``ecc fe``: hand the command line to the ECC-FE frontend, unchanged.

ECC-FE is a separate program with its own commands, output and exit codes.
ECC knows none of them: it finds the ``ecc-fe`` executable, tells it the name
it was reached under, and is replaced by it.
"""

import os
import shutil
import sys
from pathlib import Path

import typer

#: Directory of an ECC-FE installation that is not on ``PATH``; the executable
#: is ``bin/ecc-fe`` under it, as in a release archive or a source checkout.
ROOT_ENV = "CHIPCOMPILER_ECC_FE_ROOT"
#: Read by ``ecc-fe``: the words a user types to reach it, used in its output.
PROGRAM_ENV = "ECC_FE_PROGRAM"
#: The shell's exit status for a command that cannot be found.
EXIT_NOT_FOUND = 127


def register_fe_command(app: typer.Typer) -> None:
    app.command(
        "fe",
        help="Run the ECC-FE RTL frontend: every argument goes to `ecc-fe` unchanged",
        add_help_option=False,
        context_settings={
            "allow_extra_args": True,
            "ignore_unknown_options": True,
            "allow_interspersed_args": False,
        },
    )(fe_cmd)


def find_ecc_fe() -> str | None:
    """``bin/ecc-fe`` under ``CHIPCOMPILER_ECC_FE_ROOT`` first, then ``PATH``.

    Same order as the other external tools (Yosys, Sizer). A root without an
    executable ``bin/ecc-fe`` does not hide an installation on ``PATH``.
    """
    root = os.environ.get(ROOT_ENV, "").strip()
    if root:
        executable = Path(root).expanduser() / "bin" / "ecc-fe"
        if executable.is_file() and os.access(executable, os.X_OK):
            return str(executable)
    return shutil.which("ecc-fe")


def fe_cmd(ctx: typer.Context) -> None:
    executable = find_ecc_fe()
    if executable is None:
        typer.echo(
            "ecc: error: ecc-fe was not found; install ECC-FE and put `ecc-fe` on PATH, "
            f"or set {ROOT_ENV} to its installation directory",
            err=True,
        )
        raise typer.Exit(EXIT_NOT_FOUND)
    env = {**os.environ, PROGRAM_ENV: "ecc fe"}
    if getattr(sys, "frozen", False):
        # A packaged ECC runs with the loader path of its bundle; ECC-FE gets
        # the one ECC was started with.
        original = env.pop("LD_LIBRARY_PATH_ORIG", None)
        if original is None:
            env.pop("LD_LIBRARY_PATH", None)
        else:
            env["LD_LIBRARY_PATH"] = original
    os.execve(executable, [executable, *ctx.args], env)
