"""Render the bundled CLI guide documents in the terminal."""

import sys
from enum import Enum
from typing import Annotated

import typer

from chipcompiler.cli.core import docs
from chipcompiler.cli.rendering.pretty import supports_color


class DocTopic(str, Enum):
    config = "config"
    ug = "ug"
    tutorial = "tutorial"
    dev = "dev"


class DocLanguage(str, Enum):
    en = "en"
    cn = "cn"


def register_doc_commands(app: typer.Typer) -> None:
    app.command("doc", help="Show a bundled guide (config/ug/tutorial/dev) in the terminal")(
        doc_cmd
    )


def doc_cmd(
    topic: Annotated[DocTopic, typer.Argument(help="Guide to show")],
    *,
    lang: Annotated[DocLanguage, typer.Option("--lang", help="Guide language")] = DocLanguage.en,
    plain: Annotated[
        bool,
        typer.Option("--plain", help="Print the raw markdown instead of the rendered layout"),
    ] = False,
) -> None:
    try:
        raw = docs.load_guide(topic.value, lang.value)
        if plain:
            _write_plain(raw)
            return
        text = raw.decode("utf-8")
    except docs.GuideNotFoundError as exc:
        typer.echo(f"Error: {exc}", err=True)
        raise typer.Exit(1) from None
    except UnicodeDecodeError:
        typer.echo(
            f"Error: guide is not valid UTF-8: {docs.GUIDE_STEMS[topic.value]}.{lang.value}.md",
            err=True,
        )
        raise typer.Exit(1) from None
    except OSError as exc:
        typer.echo(f"Error: could not read guide: {exc}", err=True)
        raise typer.Exit(1) from None

    from chipcompiler.cli.rendering.render import render_markdown

    try:
        render_markdown(text, color=supports_color(), pager=True)
    except UnicodeEncodeError:
        typer.echo(
            "Error: terminal encoding cannot render this guide; try --plain",
            err=True,
        )
        raise typer.Exit(1) from None


def _write_plain(data: bytes) -> None:
    stream = getattr(sys.stdout, "buffer", None)
    if stream is None:
        sys.stdout.write(data.decode("utf-8"))
    else:
        stream.write(data)
        stream.flush()
