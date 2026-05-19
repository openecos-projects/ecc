import sys
from collections.abc import Sequence


def run(argv: Sequence[str] | None = None) -> int:
    raw = list(argv) if argv is not None else sys.argv[1:]

    if raw and raw[0] == "workspace":
        from chipcompiler.cli.workspace_app import run_workspace_app
        return run_workspace_app(raw[1:])

    from chipcompiler.cli.workspace_legacy import (
        is_legacy_workspace_args,
        run_legacy_workspace,
    )

    if is_legacy_workspace_args(raw):
        return run_legacy_workspace(raw)

    from chipcompiler.cli.app import invoke_typer_app
    return invoke_typer_app(raw)


def main() -> None:
    sys.exit(run())


if __name__ == "__main__":
    main()
