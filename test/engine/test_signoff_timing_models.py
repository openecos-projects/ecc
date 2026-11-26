from pathlib import Path

import pytest

from chipcompiler.engine.signoff import SignoffPackageOptions
from test.test_signoff_package import _make_engine_flow, _make_signoff_workspace, _write


@pytest.mark.parametrize("materialize", [False, True])
def test_signoff_package_includes_per_scenario_macro_models(tmp_path, materialize):
    workspace = _make_signoff_workspace(tmp_path)
    models = {
        "TYP_25/TYPICAL/gcd.lib": "tt model",
        "MIN_m40/Cbest/gcd.lib": "ff cbest model",
        "manifest.json": '{"schema_version":1,"models":[]}',
    }
    for relative, content in models.items():
        _write(workspace / "harden_ecc/output/timing_models" / relative, content)
    result = _make_engine_flow(workspace).collect_signoff_package(
        SignoffPackageOptions(materialize=materialize)
    )
    assert result.ok
    target = Path(result.package_dir) / "harden/timing_models"
    if materialize:
        assert {
            path.relative_to(target).as_posix(): path.read_text()
            for path in target.rglob("*")
            if path.is_file()
        } == models
    else:
        assert not target.exists()
