import importlib.util
import sys
from pathlib import Path


def test_conftest_loads_pdk_runtime_from_local_test_directory(tmp_path, monkeypatch):
    repo_root = Path(__file__).resolve().parents[1]
    fake_stdlib = tmp_path / "stdlib"
    fake_test_pkg = fake_stdlib / "test"
    fake_test_pkg.mkdir(parents=True)
    (fake_test_pkg / "__init__.py").write_text("", encoding="utf-8")

    monkeypatch.setattr(
        sys,
        "path",
        [
            str(repo_root),
            str(fake_stdlib),
            *[path for path in sys.path if path not in {str(repo_root), str(fake_stdlib)}],
        ],
    )
    for name in ("test", "test.pdk_runtime"):
        monkeypatch.delitem(sys.modules, name, raising=False)

    spec = importlib.util.spec_from_file_location(
        "conftest_import_check",
        repo_root / "test" / "conftest.py",
    )
    assert spec is not None
    assert spec.loader is not None
    module = importlib.util.module_from_spec(spec)

    spec.loader.exec_module(module)

    assert module.complete_ics55_pdk_available.__module__ == "pdk_runtime"
