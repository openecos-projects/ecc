from typing import Annotated

import typer

ProjectOption = Annotated[str | None, typer.Option("--project")]
JsonOption = Annotated[bool, typer.Option("--json")]
JsonlOption = Annotated[bool, typer.Option("--jsonl")]
PlainOption = Annotated[bool, typer.Option("--plain")]
RunIdOption = Annotated[str | None, typer.Option("--run-id")]
