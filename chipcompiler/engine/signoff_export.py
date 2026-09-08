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
        try:
            result = EngineFlow(workspace).collect_signoff_package(
                SignoffPackageOptions(
                    output_dir=temporary_root,
                    archive=False,
                    include_debug=include_debug,
                    materialize=False,
                    refresh_analysis=False,
                )
            )
        except (OSError, ValueError, TypeError, KeyError) as exc:
            raise SignoffExportError(str(exc)) from exc
        if not result.ok:
            missing = ", ".join(result.missing_required) or "unknown required resources"
            raise SignoffExportError(f"signoff package is incomplete: {missing}")
        if not result.package_dir:
            raise SignoffExportError("signoff package directory was not created")

        package_dir = Path(result.package_dir)

        if additional_files is not None and not isinstance(additional_files, list):
            raise SignoffExportError("additional_files must be a list")
        if additional_files:
            for file_info in additional_files:
                if not isinstance(file_info, dict):
                    raise SignoffExportError("additional file entries must be objects")
                archive_path = file_info.get("archivePath")
                content = file_info.get("content")
                if not isinstance(archive_path, str) or not archive_path:
                    raise SignoffExportError("additional file entries require archivePath")
                if not isinstance(content, str):
                    raise SignoffExportError("additional file entries require string content")
                path = _additional_file_path(package_dir, archive_path)
                path.parent.mkdir(parents=True, exist_ok=True)
                if _has_symlink_parent(package_dir, path):
                    raise SignoffExportError("additional file path contains a symlink")
                path.write_text(content, encoding="utf-8")

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


def _additional_file_path(package_dir: Path, archive_path: str) -> Path:
    relative = Path(archive_path)
    if not archive_path or relative.is_absolute() or ".." in relative.parts:
        raise SignoffExportError("additional file path must stay inside the signoff package")
    destination = (package_dir / relative).resolve()
    if not destination.is_relative_to(package_dir.resolve()):
        raise SignoffExportError("additional file path must stay inside the signoff package")
    return destination


def _has_symlink_parent(package_dir: Path, path: Path) -> bool:
    current = package_dir
    for component in path.relative_to(package_dir).parts:
        current /= component
        if current.is_symlink():
            return True
    return False
