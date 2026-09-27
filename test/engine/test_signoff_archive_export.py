import tarfile
from pathlib import Path
from types import SimpleNamespace

import pytest

from chipcompiler.engine import signoff_export
from chipcompiler.engine.signoff_export import SignoffExportError


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
