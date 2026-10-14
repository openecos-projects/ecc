import json
from typing import Annotated

import typer

from chipcompiler.cli.core.version_info import build_identity, ecc_version
from chipcompiler.update_check import (
    INSTALLER_URLS,
    STATUS_UP_TO_DATE,
    UpdateCheckResult,
    check_for_update,
)


def register_check_update_command(app) -> None:
    app.command("check-update", help="Check whether a newer nightly build is available")(
        check_update_cmd
    )


def check_update_cmd(
    *,
    # Machine-readable output for the desktop app; not part of the documented CLI surface.
    json_output: Annotated[bool, typer.Option("--json", hidden=True)] = False,
) -> None:
    build_commit, build_date = build_identity()
    result = check_for_update(ecc_version(), build_commit, build_date)
    if json_output:
        typer.echo(json.dumps(update_check_payload(result)))
    else:
        typer.echo(render_update_check(result))


def update_check_payload(result: UpdateCheckResult) -> dict:
    latest = None
    if result.latest is not None:
        latest = {
            "tag": result.latest.tag,
            "date": str(result.latest.date),
            "ecc_version": result.latest.ecc_version,
            "ecc_commit": result.latest.ecc_commit,
        }
    return {
        "schema_version": 1,
        "status": result.status,
        "current": {
            "version": result.current_version,
            "build_commit": result.current_commit,
            "build_date": result.current_build_date,
        },
        "latest": latest,
        "installer_urls": list(INSTALLER_URLS),
    }


def render_update_check(result: UpdateCheckResult) -> str:
    current = result.current_version
    if result.current_build_date and result.current_commit:
        nightly = format_date(result.current_build_date)
        short_commit = result.current_commit[:7]
        current = f"{current} (nightly {nightly}, g{short_commit})"
    lines = [f"Current version : {current}"]
    if result.latest is not None:
        latest = result.latest
        latest_label = latest.ecc_version or latest.tag
        lines.append(f"Latest nightly  : {latest_label} ({format_date(str(latest.date))})")
    lines.append(f"Status          : {result.status.replace('_', ' ')}")
    if result.status != STATUS_UP_TO_DATE:
        lines.append("")
        lines.append("Get the latest nightly build:")
        lines.extend(f"  {url}" for url in INSTALLER_URLS)
    return "\n".join(lines)


def format_date(yyyymmdd: str) -> str:
    return f"{yyyymmdd[:4]}-{yyyymmdd[4:6]}-{yyyymmdd[6:8]}"
