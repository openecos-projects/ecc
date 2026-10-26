import json

from ecc_experience.api import collect


def _bind(workspace, input_file):
    path = workspace / "home/engineering-snapshot.json"
    snapshot = json.loads(path.read_text())
    snapshot["workspaceSpec"] = {
        "design": {"topModule": "top"},
        "inputs": [{"inputId": "rtl", "role": "rtl"}],
    }
    snapshot["workspaceBindings"] = {"inputs": {"rtl": str(input_file)}}
    path.write_text(json.dumps(snapshot))


def test_complete_filelist_and_include_closure_contributes_to_input_identity(
    workspace_factory, tmp_path
):
    workspace = workspace_factory("closure-complete")
    rtl = tmp_path / "rtl"
    rtl.mkdir()
    top = rtl / "top.v"
    top.write_text('`include "defs.vh"\nmodule top; endmodule\n')
    (rtl / "defs.vh").write_text("`define WIDTH 8\n")
    filelist = rtl / "files.f"
    filelist.write_text("+incdir+.\ntop.v\n")
    _bind(workspace, filelist)

    case = collect(workspace, tmp_path / "store").case

    assert case.inputs[0].closure == "complete"
    assert case.inputs[0].resolved_files == 3
    assert case.inputs[0].closure_sha256
    assert case.design.closure == "complete"
    assert case.input_content_fingerprint
    first = case.input_content_fingerprint
    (rtl / "defs.vh").write_text("`define WIDTH 16\n")
    changed = collect(workspace, tmp_path / "store").case
    assert changed.input_content_fingerprint != first


def test_missing_include_is_partial_and_never_strictly_usable(workspace_factory, tmp_path):
    workspace = workspace_factory("closure-partial")
    top = tmp_path / "top.v"
    top.write_text('`include "missing.vh"\nmodule top; endmodule\n')
    _bind(workspace, top)

    case = collect(workspace, tmp_path / "store").case

    assert case.inputs[0].closure == "partial"
    assert case.design.closure == "partial"
    assert case.input_content_fingerprint is None
    assert any("include_unresolved" in item for item in case.limitations)


def test_unreadable_binding_is_unknown(workspace_factory, tmp_path):
    workspace = workspace_factory("closure-unknown")
    _bind(workspace, tmp_path / "absent.v")

    case = collect(workspace, tmp_path / "store").case

    assert case.inputs[0].closure == "unknown"
    assert case.design.closure == "unknown"
    assert case.input_content_fingerprint is None


def test_filelist_unsupported_directive_is_partial_not_silently_ignored(
    workspace_factory, tmp_path
):
    workspace = workspace_factory("closure-directive")
    top = tmp_path / "top.v"
    top.write_text("module top; endmodule\n")
    filelist = tmp_path / "files.f"
    filelist.write_text("-y /external/library\ntop.v\n")
    _bind(workspace, filelist)

    case = collect(workspace, tmp_path / "store").case

    assert case.inputs[0].closure == "partial"
    assert any("library_directory_unsupported" in item for item in case.limitations)
