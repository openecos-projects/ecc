import sys
from collections.abc import Sequence


def run(
    argv: Sequence[str] | None = None,
    *,
    _keep_workspace_json_stdio_redirect: bool = False,
) -> int:
    raw = list(argv) if argv is not None else sys.argv[1:]

    from chipcompiler.cli.app import invoke_typer_app

    return invoke_typer_app(
        raw,
        keep_workspace_json_stdio_redirect=_keep_workspace_json_stdio_redirect,
    )


def main() -> None:
    sys.exit(run(_keep_workspace_json_stdio_redirect=True))


if __name__ == "__main__":
    main()
