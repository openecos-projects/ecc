import shutil
import subprocess
import zipfile
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).parents[2]


@pytest.mark.skipif(shutil.which("uv") is None, reason="uv is required to build the wheel")
def test_wheel_ships_all_doc_guides(tmp_path):
    subprocess.run(
        ["uv", "build", "--wheel", "--out-dir", str(tmp_path)],
        cwd=REPO_ROOT,
        check=True,
        capture_output=True,
    )

    wheel = next(tmp_path.glob("ecc-*.whl"))
    names = zipfile.ZipFile(wheel).namelist()
    for stem in ("config-ref", "user-guide", "tutorial"):
        for lang in ("en", "cn"):
            assert f"chipcompiler/docs/ecc-{stem}.{lang}.md" in names
