import hashlib
import json
from pathlib import Path

import pytest

from chipcompiler.cli.project.fe_handoff import import_fe_handoff
from chipcompiler.cli.project.rtl_import import RtlImportError
from chipcompiler.cli.project.timing_template import SDC_INPUT_FILENAME, SDC_INPUT_TEMPLATE

_TOML = '[design]\nname = "demo"\ntop = "demo"\nrtl = []\n'


def _project(root: Path, toml: str = _TOML) -> Path:
    root.mkdir(parents=True)
    (root / "ecc.toml").write_text(toml, encoding="utf-8")
    (root / "project.json").write_text(
        json.dumps({"schema_version": 1, "name": "demo", "base_design": {}, "workspaces": []}),
        encoding="utf-8",
    )
    return root


def _entry(path: Path, listed: str) -> dict:
    return {"path": listed, "sha256": hashlib.sha256(path.read_bytes()).hexdigest()}


def _handoff(directory: Path, tree: Path, *, bundled: bool = False, **changes) -> Path:
    """A version 1 manifest for the design below *tree*, as ``ecc-fe handoff`` writes it."""

    def listed(path: Path) -> str:
        return str(path.relative_to(directory)) if bundled else str(path)

    document = {
        "schema_version": 1,
        "kind": "ecc-fe-handoff",
        "generator": {"name": "ecc-fe", "version": "0.1.0"},
        "source": {"project": "/fe/project", "run": "default", "workspace": "/fe/run"},
        "design": {
            "name": "core",
            "kind": "rtl",
            "top": "core",
            "clock_port": "clock",
            "frequency_mhz": 50.0,
            "parameters": ["WIDTH=8"],
            "sdc": None,
        },
        "rtl": {
            "bundled": bundled,
            "root": "rtl" if bundled else None,
            "files": [
                _entry(tree / "a/util.sv", listed(tree / "a/util.sv")),
                _entry(tree / "b/util.sv", listed(tree / "b/util.sv")),
            ],
            "headers": [_entry(tree / "inc/bus/defs.svh", listed(tree / "inc/bus/defs.svh"))],
            "incdirs": [listed(tree / "a"), listed(tree / "b"), listed(tree / "inc")],
            "libdirs": [],
            "libexts": [],
            "defines": ["FAST", "DEPTH=4"],
            "filelist": "design.f",
        },
        "flow": {"status": "complete", "state": "success", "blockers": []},
    }
    for dotted, value in changes.items():
        table, _, name = dotted.partition("__")
        if name:
            document[table][name] = value
        else:
            document[table] = value
    directory.mkdir(parents=True, exist_ok=True)
    path = directory / "handoff.json"
    path.write_text(json.dumps(document), encoding="utf-8")
    return path


def _design(root: Path) -> Path:
    for name, text in {
        "a/util.sv": '`include "bus/defs.svh"\nmodule core; endmodule\n',
        "b/util.sv": "module util; endmodule\n",
        "inc/bus/defs.svh": "`define BUS 1\n",
        "a/unrelated.txt": "not part of the design\n",
    }.items():
        (root / name).parent.mkdir(parents=True, exist_ok=True)
        (root / name).write_text(text, encoding="utf-8")
    return root


def _files(root: Path) -> list[str]:
    return sorted(str(path.relative_to(root)) for path in root.rglob("*") if path.is_file())


_FILELIST = (
    "# Imported from an ECC-FE handoff (ecc-fe 0.1.0, run default).\n"
    "+incdir+a\n"
    "+incdir+b\n"
    "+incdir+inc\n"
    "+define+FAST\n"
    "+define+DEPTH=4\n"
    "-G WIDTH=8\n"
    "a/util.sv\n"
    "b/util.sv\n"
)


def test_import_copies_what_the_manifest_lists_and_declares_it(tmp_path):
    project = _project(tmp_path / "project")
    manifest = _handoff(tmp_path / "handoff", _design(tmp_path / "design"))

    records = import_fe_handoff(str(project), str(manifest))

    # Equally named sources keep their directories; a file the manifest does not list stays.
    assert _files(project / "rtl") == ["a/util.sv", "b/util.sv", "design.f", "inc/bus/defs.svh"]
    assert (project / "rtl/design.f").read_text() == _FILELIST
    assert records == [
        {
            "project": str(project),
            "status": "rtl_imported",
            "filelist": "rtl/design.f",
            "rtl": ["rtl/a/util.sv", "rtl/b/util.sv"],
            "include_dirs": ["rtl/a", "rtl/b", "rtl/inc"],
            "top": "core",
            "clock_port": "clock",
            "handoff": str(manifest),
            "frontend": "ecc-fe 0.1.0",
        }
    ]
    toml = (project / "ecc.toml").read_text()
    assert 'rtl = ["rtl/design.f"]' in toml
    assert 'top = "core"' in toml
    assert 'clock_port = "clock"' in toml
    assert json.loads((project / "project.json").read_text())["base_design"] == {
        "rtl_list": ["rtl/a/util.sv", "rtl/b/util.sv"],
        "top_module": "core",
        "clock": "clock",
        "origin_verilog": "rtl/a/util.sv",
        "origin_filelist": "rtl/design.f",
    }


def test_import_reads_a_bundle_by_its_directory(tmp_path):
    project = _project(tmp_path / "project")
    bundle = tmp_path / "export"
    _handoff(bundle, _design(bundle / "rtl"), bundled=True)

    import_fe_handoff(str(project), str(bundle))

    assert (project / "rtl/design.f").read_text() == _FILELIST


def test_import_keeps_an_include_directory_above_the_sources(tmp_path):
    project = _project(tmp_path / "project")
    design = _design(tmp_path / "design")
    manifest = _handoff(
        tmp_path / "handoff",
        design,
        rtl__files=[_entry(design / "a/util.sv", str(design / "a/util.sv"))],
        rtl__headers=[],
        rtl__incdirs=[str(design), str(tmp_path / "elsewhere")],
        rtl__defines=[],
        design__parameters=[],
    )

    import_fe_handoff(str(project), str(manifest))

    # `include "a/..."` through the directory above still resolves; a
    # directory that holds nothing of the design is not carried over.
    assert (project / "rtl/design.f").read_text() == (
        "# Imported from an ECC-FE handoff (ecc-fe 0.1.0, run default).\n+incdir+.\na/util.sv\n"
    )


def test_import_without_a_known_clock_leaves_the_clock_port(tmp_path):
    project = _project(tmp_path / "project")
    manifest = _handoff(tmp_path / "handoff", _design(tmp_path / "design"), design__clock_port=None)

    import_fe_handoff(str(project), str(manifest))

    assert "clock_port" not in (project / "ecc.toml").read_text()


def test_import_warns_when_the_timing_input_constrains_another_port(tmp_path):
    project = _project(tmp_path / "project", _TOML + f'sdc = "{SDC_INPUT_FILENAME}"\n')
    (project / SDC_INPUT_FILENAME).write_text(SDC_INPUT_TEMPLATE, encoding="utf-8")
    manifest = _handoff(tmp_path / "handoff", _design(tmp_path / "design"))

    warning, _result = import_fe_handoff(str(project), str(manifest))

    assert warning == {
        "kind": "warning",
        "warning": "clock_port_mismatch",
        "clock_port": "clock",
        "constrained_port": "clk",
        "timing_input": SDC_INPUT_FILENAME,
        "reason": "the timing input declares the primary clock on another port "
        "than the clock of the imported design; edit its primary_clocks",
    }


def _changed(design: Path) -> None:
    (design / "b/util.sv").write_text("module util; wire late_edit; endmodule\n")


def _removed(design: Path) -> None:
    (design / "inc/bus/defs.svh").unlink()


@pytest.mark.parametrize(
    ("changes", "after", "code"),
    [
        ({"kind": "something-else"}, None, "fe_handoff_invalid"),
        ({"schema_version": 2}, None, "fe_handoff_unsupported_version"),
        (
            {"flow": {"status": "incomplete", "blockers": [{"step": "lint", "reason": "failed"}]}},
            None,
            "fe_handoff_incomplete",
        ),
        ({"rtl__libdirs": ["/lib/cells"]}, None, "fe_handoff_unsupported"),
        ({"design": {"name": "core"}}, None, "fe_handoff_invalid"),
        ({"rtl__files": []}, None, "fe_handoff_invalid"),
        ({}, _changed, "fe_handoff_file_changed"),
        ({}, _removed, "fe_handoff_file_missing"),
    ],
)
def test_import_refuses_a_manifest_it_cannot_honour(tmp_path, changes, after, code):
    project = _project(tmp_path / "project")
    design = _design(tmp_path / "design")
    manifest = _handoff(tmp_path / "handoff", design, **changes)
    if after:
        after(design)

    with pytest.raises(RtlImportError) as error:
        import_fe_handoff(str(project), str(manifest))

    assert error.value.code == code
    # Refused before anything is written.
    assert _files(project) == ["ecc.toml", "project.json"]
    assert (project / "ecc.toml").read_text() == _TOML


def test_import_reports_a_manifest_that_is_not_there(tmp_path):
    project = _project(tmp_path / "project")

    with pytest.raises(RtlImportError) as error:
        import_fe_handoff(str(project), str(tmp_path / "nowhere"))

    assert error.value.code == "fe_handoff_not_found"


def test_import_replaces_an_earlier_import_only_with_force(tmp_path):
    project = _project(tmp_path / "project")
    manifest = _handoff(tmp_path / "handoff", _design(tmp_path / "design"))
    import_fe_handoff(str(project), str(manifest))

    with pytest.raises(RtlImportError) as error:
        import_fe_handoff(str(project), str(manifest))
    assert error.value.code == "rtl_target_exists"

    import_fe_handoff(str(project), str(manifest), force=True)
    assert (project / "rtl/design.f").read_text() == _FILELIST
