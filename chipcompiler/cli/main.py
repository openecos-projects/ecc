import sys
from collections.abc import Sequence


def run(
    argv: Sequence[str] | None = None,
) -> int:
    raw = list(argv) if argv is not None else sys.argv[1:]
    if raw[:1] == ["_experience-command-worker"]:
        from ecc_experience.command_worker import main as command_worker

        return command_worker(raw[1:])

    from chipcompiler.cli.app import invoke_typer_app

    return invoke_typer_app(raw)


def main() -> None:
    sys.exit(run())


if __name__ == "__main__":
    main()
