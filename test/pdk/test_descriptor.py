import json

import pytest
from typer.testing import CliRunner

from chipcompiler.cli.commands.pdk_configure import configure_app
from chipcompiler.pdk.configuration import replace_field, write_descriptor
from chipcompiler.pdk.manifest import (
    Descriptor,
    DescriptorError,
    Resource,
    content_identity,
    load_descriptor,
)
from chipcompiler.pdk.validation import validate_resources


def test_missing_description_never_infers_ics55(tmp_path):
    with pytest.raises(DescriptorError, match="ecc pdk configure init") as error:
        load_descriptor(tmp_path)
    assert error.value.code == "pdk_descriptor_missing"


def test_checksum_catches_same_path_changed_content(tmp_path):
    path = tmp_path / "cells.lib"
    path.write_text("library(one) {}")
    descriptor = Descriptor(
        family_id="custom", resources={"cells": Resource(path=path.name, role="liberty")}
    )
    before, hashes = content_identity(tmp_path, descriptor)
    path.write_text("library(two) {}")
    assert content_identity(tmp_path, descriptor)[0] != before
    pinned = descriptor.model_copy(
        update={
            "resources": {"cells": Resource(path=path.name, role="liberty", sha256=hashes["cells"])}
        }
    )
    with pytest.raises(DescriptorError, match="checksum"):
        content_identity(tmp_path, pinned)


def test_resource_symlink_escape_is_rejected(tmp_path):
    root = tmp_path / "pdk"
    root.mkdir()
    outside = tmp_path / "outside.lib"
    outside.write_text("library() {}")
    (root / "cells.lib").symlink_to(outside)
    descriptor = Descriptor(
        family_id="custom", resources={"cells": Resource(path="cells.lib", role="liberty")}
    )
    assert validate_resources(root, descriptor)["diagnostics"][0]["code"] == "resource_outside_root"


def test_partial_package_reports_resources_not_backend_qualification(tmp_path):
    (tmp_path / "cells.lib").write_text("library() {}")
    descriptor = Descriptor(
        family_id="example", resources={"cells": Resource(path="cells.lib", role="liberty")}
    )
    report = validate_resources(tmp_path, descriptor)
    assert report["stages"]["synthesis"] == {
        "resources_ready": True,
        "missing_roles": [],
        "backend_support": "unchecked",
        "qualification": "unverified",
    }
    assert report["stages"]["routing"]["missing_roles"] == ["lef", "tech"]


def test_atomic_edit_rejects_stale_revision_and_preserves_file(tmp_path):
    path = tmp_path / "ecc-pdk.json"
    initial = Descriptor(family_id="example")
    revision = write_descriptor(path, initial, create=True)
    changed = replace_field(initial, "release", "second")
    write_descriptor(path, changed, expected_digest=revision)
    with pytest.raises(DescriptorError, match="reload"):
        write_descriptor(path, initial, expected_digest=revision)
    assert load_descriptor(tmp_path) == changed
    with pytest.raises(DescriptorError, match="exists"):
        write_descriptor(path, initial, create=True)


def test_cli_authoring_round_trip(tmp_path):
    runner = CliRunner()
    root = ["--root", str(tmp_path)]
    created = runner.invoke(configure_app, ["init", *root, "--family", "ics55"])
    assert created.exit_code == 0, created.output
    revision = json.loads(created.output)["revision"]
    edited = runner.invoke(
        configure_app,
        [
            "set",
            *root,
            "--field",
            "cells.buffers",
            "--value-json",
            '["BUF_other"]',
            "--expected-revision",
            revision,
        ],
    )
    assert edited.exit_code == 0, edited.output
    shown = runner.invoke(configure_app, ["show", *root])
    assert json.loads(shown.output)["descriptor"]["cells"]["buffers"] == ["BUF_other"]
    assert runner.invoke(configure_app, ["init", *root, "--family", "other"]).exit_code == 2


@pytest.mark.parametrize(
    "patch", [{"schema_version": 2}, {"unexpected": 1}, {"synthesis_libraries": ["missing"]}]
)
def test_invalid_contract_rejected(patch):
    with pytest.raises(ValueError):
        Descriptor.model_validate({"family_id": "example", **patch})


def test_resolver_uses_description_without_family_defaults(tmp_path):
    from chipcompiler.data.pdk import get_pdk

    for filename in ("technology.lef", "cells.lef", "slow.lib"):
        (tmp_path / filename).write_text("fixture")
    descriptor = Descriptor(
        family_id="different",
        release="r1",
        resources={
            "tech": Resource(path="technology.lef", role="tech"),
            "cells": Resource(path="cells.lef", role="lef"),
            "slow": Resource(path="slow.lib", role="liberty"),
        },
    )
    write_descriptor(tmp_path / "ecc-pdk.json", descriptor, create=True)
    pdk = get_pdk("different", tmp_path)
    assert pdk.buffers == []
    assert pdk.site_core == ""
    assert pdk.tech == tmp_path / "technology.lef"
    assert pdk.libs == [tmp_path / "slow.lib"]
    assert pdk.version == "r1"
    with pytest.raises(DescriptorError, match="description declares"):
        get_pdk("ics55", tmp_path)


def test_explicit_ics55_root_without_descriptor_has_no_builtin_fallback(tmp_path):
    from chipcompiler.data.pdk import get_pdk

    with pytest.raises(DescriptorError, match="description is missing"):
        get_pdk("ics55", tmp_path, validate=False)


def test_liberty_only_workspace_can_be_created_without_physical_defaults(tmp_path):
    from chipcompiler.data.workspace import create_workspace
    from chipcompiler.pdk.capabilities import stage_diagnostics

    root = tmp_path / "vendor"
    root.mkdir()
    (root / "cells.lib").write_text("library(vendor) {}")
    description = Descriptor(
        family_id="vendor",
        resources={"lib": Resource(path="cells.lib", role="liberty")},
        synthesis_libraries=["lib"],
    )
    write_descriptor(root / "ecc-pdk.json", description, create=True)
    rtl = tmp_path / "top.v"
    rtl.write_text("module top(input a, output y); assign y=a; endmodule")
    sdc = tmp_path / "constraints.sdc"
    sdc.write_text("set_units -time ns\n")
    workspace = create_workspace(
        directory=tmp_path / "ws",
        origin_def="",
        origin_verilog=rtl,
        pdk="vendor",
        pdk_root=root,
        sdc=sdc,
        parameters={"design": "top", "top_module": "top", "frequency_max": 100.0},
        flow_config={"steps": ["Synthesis"]},
    )
    assert workspace is not None
    assert stage_diagnostics(workspace.pdk, ["Synthesis"]) == []
    assert stage_diagnostics(workspace.pdk, ["route"])
    assert workspace.pdk.tech is None
    assert workspace.pdk.buffers == []


def test_resolved_context_reports_selected_site_and_database_units(tmp_path):
    from chipcompiler.pdk.context import resolved_context

    (tmp_path / "tech.lef").write_text(
        "UNITS DATABASE MICRONS 2000 ; END UNITS\n"
        "MACRO example SITE selected ; SIZE 99 BY 99 ; END example\n"
        "SITE selected SIZE 0.25 BY 1.0 ; END selected\n"
        "SITE unused SIZE 0.5 BY 2.0 ; END unused\n"
    )
    description = Descriptor.model_validate(
        {
            "family_id": "vendor",
            "cells": {"site_core": "selected"},
            "resources": {"tech": {"path": "tech.lef", "role": "tech"}},
        }
    )
    context = resolved_context(tmp_path, description)
    assert context["database_units_per_micron"] == 2000
    assert context["site_width_dbu"] == 500
