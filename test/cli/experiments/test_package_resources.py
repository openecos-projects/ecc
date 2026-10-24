import io
import json
import tarfile

import pytest

from chipcompiler.cli.experiments.operations import read_package


@pytest.mark.parametrize("manifest", [None, b"{broken", b'{"schema_version": 1}', b"[]", b"null"])
def test_package_reader_closes_archive_on_success_and_invalid_manifest(
    tmp_path, monkeypatch, manifest
):
    package = tmp_path / "package.tar.gz"
    with tarfile.open(package, "w:gz") as archive:
        if manifest is not None:
            member = tarfile.TarInfo("./manifest.json")
            member.size = len(manifest)
            archive.addfile(member, io.BytesIO(manifest))
    opened = []
    original_open = tarfile.open

    def tracked_open(*args, **kwargs):
        archive = original_open(*args, **kwargs)
        opened.append(archive)
        return archive

    monkeypatch.setattr(tarfile, "open", tracked_open)
    if manifest is None or manifest in {b"{broken", b"[]", b"null"}:
        with pytest.raises((ValueError, json.JSONDecodeError)), read_package(package):
            pytest.fail("invalid manifest was accepted")
    else:
        with read_package(package) as (archive, document):
            assert document == {"schema_version": 1}
            assert not archive.closed
    assert len(opened) == 1
    assert opened[0].closed
