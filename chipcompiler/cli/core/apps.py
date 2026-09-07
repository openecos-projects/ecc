import typer


def create_app(*, help: str) -> typer.Typer:
    return typer.Typer(
        add_completion=False,
        no_args_is_help=True,
        rich_markup_mode=None,
        help=help,
    )
