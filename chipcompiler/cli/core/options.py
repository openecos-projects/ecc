from typing import Annotated

import typer

ProjectOption = Annotated[
    str | None,
    typer.Option("--project", help="Project directory (default: current project directory)"),
]
PlainOption = Annotated[bool, typer.Option("--plain")]
JsonOption = Annotated[bool, typer.Option("--json")]
WorkspaceOption = Annotated[
    str | None,
    typer.Option(
        "--workspace", help="Managed workspace name or absolute path (default: current workspace)"
    ),
]
