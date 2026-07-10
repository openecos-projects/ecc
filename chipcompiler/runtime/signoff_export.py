from __future__ import annotations

import os
import shutil
import tempfile
from pathlib import Path

from chipcompiler.engine import EngineFlow, SignoffPackageOptions
from chipcompiler.runtime.workspace_api import RuntimeApiError


def export_signoff_package_archive(workspace, output_path: str) -> str:
    raw_destination = Path(output_path).expanduser()
    destination = raw_destination.parent.resolve() / raw_destination.name

    with tempfile.TemporaryDirectory(prefix="ecc-signoff-") as temporary_root:
        result = EngineFlow(workspace).collect_signoff_package(
            SignoffPackageOptions(output_dir=temporary_root, archive=True)
        )
        if not result.ok:
            missing = ", ".join(result.missing_required) or "unknown required resources"
            raise RuntimeApiError(
                "command_failed",
                f"signoff package is incomplete: {missing}",
            )
        if not result.archive_path:
            raise RuntimeApiError(
                "command_failed",
                "signoff package archive was not created",
            )

        archive = Path(result.archive_path)
        if not archive.is_file():
            raise RuntimeApiError(
                "command_failed",
                f"signoff package archive does not exist: {archive}",
            )

        destination.parent.mkdir(parents=True, exist_ok=True)
        descriptor, staged_name = tempfile.mkstemp(
            dir=destination.parent,
            prefix=f".{destination.name}.",
        )
        os.close(descriptor)
        staged_path = Path(staged_name)
        try:
            shutil.copy2(archive, staged_path)
            os.replace(staged_path, destination)
        finally:
            staged_path.unlink(missing_ok=True)

    return str(destination)
