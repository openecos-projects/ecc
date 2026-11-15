import shutil

import pytest

from chipcompiler.pdk.locking import bind_project, read_lock, verify_lock
from chipcompiler.pdk.manifest import Descriptor, DescriptorError, Resource


def test_lock_survives_relocation_but_rejects_resource_change(tmp_path):
    root = tmp_path / "pdk"
    root.mkdir()
    (root / "library.lib").write_text("original")
    project = tmp_path / "project"
    project.mkdir()
    descriptor = Descriptor(
        family_id="example", resources={"lib": Resource(path="library.lib", role="liberty")}
    )
    lock = bind_project(project, root, descriptor)
    moved = tmp_path / "moved"
    shutil.copytree(root, moved)
    verify_lock(moved, read_lock(project / "pdk.lock.json"))
    (moved / "library.lib").write_text("modified")
    with pytest.raises(DescriptorError, match="differ"):
        verify_lock(moved, lock)
    with pytest.raises(DescriptorError, match="copy the project"):
        bind_project(project, moved, descriptor)
    assert read_lock(project / "pdk.lock.json") == lock
