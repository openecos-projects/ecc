import os
import shutil
import tempfile
from pathlib import Path

from chipcompiler.engine import EngineFlow, SignoffPackageOptions
from chipcompiler.engine.signoff_assessment import build_signoff_assessment


class SignoffExportError(RuntimeError):
    pass


def inspect_signoff_package(workspace) -> dict:
    """Return the current Signoff Assessment without mutating the Workspace."""
    return build_signoff_assessment(workspace)


def export_signoff_package_archive(
    workspace,
    output_path: str,
    additional_files: list[dict[str, str]] | None = None,
    *,
    include_debug: bool = False,
) -> str:
    raw_destination = Path(output_path).expanduser()
    destination = raw_destination.parent.resolve() / raw_destination.name

    with tempfile.TemporaryDirectory(prefix="ecc-signoff-") as temporary_root:
        result = EngineFlow(workspace).collect_signoff_package(
            SignoffPackageOptions(
                output_dir=temporary_root,
                archive=False,
                include_debug=include_debug,
                materialize=False,
                refresh_analysis=False,
            )
        )
        if not result.ok:
            missing = ", ".join(result.missing_required) or "unknown required resources"
            raise SignoffExportError(f"signoff package is incomplete: {missing}")
        if not result.package_dir:
            raise SignoffExportError("signoff package directory was not created")

        package_dir = Path(result.package_dir)

        if additional_files:
            for file_info in additional_files:
                p = package_dir / file_info["archivePath"]
                p.parent.mkdir(parents=True, exist_ok=True)
                p.write_text(file_info["content"], encoding="utf-8")

        archive = package_dir.with_suffix(".tar.gz")
        import tarfile

        with tarfile.open(archive, "w:gz") as tar:
            tar.add(package_dir, arcname=package_dir.name)

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
