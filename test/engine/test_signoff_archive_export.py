import tarfile
from pathlib import Path
from types import SimpleNamespace

import pytest

from chipcompiler.engine import signoff_export
from chipcompiler.engine.signoff_export import SignoffAdditionalFileError, SignoffExportError


def test_export_materializes_package_before_archiving(monkeypatch, tmp_path):
    output_path = tmp_path / "exports" / "design.tar.gz"
    collected_options = []

    class FakeFlow:
        def __init__(self, workspace):
            assert workspace == "workspace"

        def collect_signoff_package(self, options):
            collected_options.append(options)
            package_dir = Path(options.output_dir) / "design_signoff_package"
            if options.materialize:
                package_dir.mkdir(parents=True)
                (package_dir / "manifest.json").write_text("{}", encoding="utf-8")
            return SimpleNamespace(
                ok=True,
                package_dir=str(package_dir),
                missing_required=[],
            )

    monkeypatch.setattr(signoff_export, "EngineFlow", FakeFlow)

    result = signoff_export.export_signoff_package_archive(
        "workspace",
        str(output_path),
        include_debug=True,
    )

    assert result == str(output_path.resolve())
    assert len(collected_options) == 1
    options = collected_options[0]
    assert options.archive is False
    assert options.include_debug is True
    assert options.materialize is True
    assert options.refresh_analysis is False
    assert not Path(options.output_dir).exists()
    with tarfile.open(output_path, "r:gz") as archive:
        manifest = archive.extractfile("design_signoff_package/manifest.json")
        assert manifest is not None
        assert manifest.read() == b"{}"


def test_export_rejects_missing_collected_package_directory(monkeypatch, tmp_path):
    class FakeFlow:
        def __init__(self, workspace):
            pass

        def collect_signoff_package(self, options):
            return SimpleNamespace(
                ok=True,
                package_dir=str(Path(options.output_dir) / "missing_signoff_package"),
                missing_required=[],
            )

    monkeypatch.setattr(signoff_export, "EngineFlow", FakeFlow)

    with pytest.raises(SignoffExportError, match="directory was not created"):
        signoff_export.export_signoff_package_archive(
            "workspace",
            str(tmp_path / "design.tar.gz"),
        )


LAYOUT = b"GDS-LAYOUT" * 64
MANIFEST = b'{"files": [{"destination": "harden/design.gds", "size_bytes": 640}]}'


def _collected_package(monkeypatch):
    """A collected package with one deliverable and the manifest that describes it."""

    class FakeFlow:
        def __init__(self, workspace):
            pass

        def collect_signoff_package(self, options):
            package_dir = Path(options.output_dir) / "design_signoff_package"
            (package_dir / "harden").mkdir(parents=True)
            (package_dir / "harden" / "design.gds").write_bytes(LAYOUT)
            (package_dir / "manifest.json").write_bytes(MANIFEST)
            return SimpleNamespace(ok=True, package_dir=str(package_dir), missing_required=[])

    monkeypatch.setattr(signoff_export, "EngineFlow", FakeFlow)


@pytest.mark.parametrize(
    "archive_path",
    [
        "harden/design.gds",  # a collected deliverable
        "manifest.json",  # the manifest that records the deliverables
        "harden",  # an existing directory of the package
        "harden/design.gds/notes.txt",  # a path that runs through a deliverable
    ],
)
def test_export_refuses_additional_file_on_a_packaged_path(monkeypatch, tmp_path, archive_path):
    _collected_package(monkeypatch)
    output_path = tmp_path / "design.tar.gz"

    with pytest.raises(SignoffAdditionalFileError, match="already used by the signoff package"):
        signoff_export.export_signoff_package_archive(
            "workspace",
            str(output_path),
            [{"archivePath": archive_path, "content": "NOT A LAYOUT\n"}],
        )

    assert not output_path.exists()


def test_export_refuses_two_additional_files_on_one_path(monkeypatch, tmp_path):
    _collected_package(monkeypatch)
    output_path = tmp_path / "design.tar.gz"

    with pytest.raises(SignoffAdditionalFileError, match="already used by the signoff package"):
        signoff_export.export_signoff_package_archive(
            "workspace",
            str(output_path),
            [
                {"archivePath": "notes/readme.txt", "content": "first\n"},
                {"archivePath": "notes/./readme.txt", "content": "second\n"},
            ],
        )

    assert not output_path.exists()


def test_export_adds_additional_files_next_to_the_deliverables(monkeypatch, tmp_path):
    _collected_package(monkeypatch)
    output_path = tmp_path / "design.tar.gz"

    signoff_export.export_signoff_package_archive(
        "workspace",
        str(output_path),
        [
            {"archivePath": "design_summaries/design_summary.md", "content": "summary\n"},
            {"archivePath": "harden/notes.txt", "content": "notes\n"},
        ],
    )

    with tarfile.open(output_path, "r:gz") as archive:
        root = "design_signoff_package/"
        assert archive.extractfile(root + "harden/design.gds").read() == LAYOUT
        assert archive.extractfile(root + "manifest.json").read() == MANIFEST
        assert archive.extractfile(root + "design_summaries/design_summary.md").read() == (
            b"summary\n"
        )
        assert archive.extractfile(root + "harden/notes.txt").read() == b"notes\n"
