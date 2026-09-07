import typer


def create_app(*, help: str, add_completion: bool = False) -> typer.Typer:
    return typer.Typer(
        add_completion=add_completion,
        no_args_is_help=True,
        rich_markup_mode="markdown",
        help=help,
    )
