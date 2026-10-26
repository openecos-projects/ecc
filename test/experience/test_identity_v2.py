import json

from ecc_experience.api import verify
from ecc_experience.knowledge.design_tags import design_tags, memory_identity
from ecc_experience.knowledge.failure import classify_failure


def _prepare_workspace(workspace, tmp_path):
    source = tmp_path / "rtl" / "top.v"
    source.parent.mkdir(parents=True)
    source.write_text('`include "defs.vh"\nmodule top; endmodule\n')
    (source.parent / "defs.vh").write_text("`define WIDTH 8\n")
    sdc = workspace / "constraints" / "top.sdc"
    sdc.parent.mkdir()
    sdc.write_text("create_clock -name clk -period 2.5 [get_ports clk]\n")
    path = workspace / "home/engineering-snapshot.json"
    snapshot = json.loads(path.read_text())
    snapshot["workspaceSpec"] = {
        "design": {
            "name": "top",
            "topModule": "top",
            "tags": [
                {"name": "datapath", "source": "spec", "confidence": "medium"},
                "memory",
            ],
            "memory": {"implementation": "mapped_macro", "bits": 1024, "macroCount": 4},
        },
        "inputs": [{"inputId": "rtl", "role": "rtl"}],
        "parameters": {"place.target_density": 0.4},
    }
    snapshot["workspaceBindings"] = {"inputs": {"rtl": str(source)}}
    snapshot["stepOutputs"]["sdc"] = {"path": "constraints/top.sdc", "exists": True}
    snapshot["flow"]["steps"].append({"name": "place", "tool": "dreamplace", "state": "Success"})
    path.write_text(json.dumps(snapshot))
    (workspace / "home/flow.json").write_text(json.dumps(snapshot["flow"]))


def test_schema_v2_captures_all_identity_dimensions_and_explains_findings(
    workspace_factory, tmp_path
):
    workspace = workspace_factory("identity-v2")
    _prepare_workspace(workspace, tmp_path)
    context = {
        "schema": "ecc-experience-execution-context/1",
        "attempt_id": "attempt-v2",
        "process": {
            "status": "available",
            "fingerprint": "selected-pdk",
            "scope": "selected_tech_lef_liberty_mapping_not_complete_pdk_closure",
            "files": [{"role": "tech", "sha256": "a" * 64, "bytes": 12}],
        },
        "runtime": {
            "ecc": "test",
            "sources": {"chipcompiler": "source"},
            "tools": {"yosys": "1"},
            "native_packages": {},
        },
    }
    from ecc_experience.adapters.chipcompiler_reader import read_workspace_observation
    from ecc_experience.collection.collect import collect_committed_case
    from ecc_experience.knowledge.store import ExperienceStore

    case = collect_committed_case(
        workspace,
        ExperienceStore(tmp_path / "store"),
        read_workspace_observation,
        attempt_id="attempt-v2",
        execution_context=context,
    ).case
    assert case.schema_version == 2
    assert case.input_content_fingerprint
    assert case.design is not None and case.design.closure == "complete"
    assert case.design.tags[0].source == "spec"
    assert case.design.memory_implementation == "mapped_macro"
    assert case.constraints is not None
    assert case.constraints.clock_periods == [2.5]
    assert case.constraints.timing_constraints_status == "available"
    assert case.process is not None and case.process.status == "available"
    assert case.toolchain is not None and case.toolchain.status == "available"
    assert case.failure.primary_category == "none"
    assert case.parameter_evidence.level == "configured"
    checks = {item.check: item.status for item in verify(case.case_id, tmp_path / "store").findings}
    assert checks["identity_design"] == "pass"
    assert checks["identity_constraints"] == "pass"
    assert checks["identity_process"] == "pass"
    assert checks["identity_toolchain"] == "pass"


def test_v1_cases_remain_readable_but_identity_is_explicitly_unknown():
    from ecc_experience.models import ExperienceCase

    payload = {
        "schema_version": 1,
        "case_id": "case-" + "0" * 64,
        "collector_version": "test",
        "collected_at": "2026-01-01T00:00:00Z",
        "source": {
            "workspace_root": "/tmp/old",
            "workspace_id": "old",
            "snapshot_schema": 3,
            "snapshot_digest": "a" * 64,
            "cause": None,
            "observation_type": "committed_import",
        },
        "input_content_fingerprint": "input",
        "inputs": [],
        "facts": {},
        "evidence": [],
        "limitations": [],
        "parameter_evidence": "configured",
        "validation_scope": "committed_observation",
    }
    case = ExperienceCase.model_validate(payload)
    assert case.schema_version == 1
    assert case.design is None


def test_failure_taxonomy_uses_structured_evidence_only():
    success = {
        "flow": {"steps": [{"name": "place", "state": "Success"}]},
    }
    assert classify_failure(success).primary_category == "none"
    assert classify_failure(success, verification_status="fail").primary_category == (
        "evidence_invalid"
    )
    timeout = {
        "flow": {
            "steps": [
                {
                    "name": "place",
                    "state": "Error",
                    "resource_observation": {"outcome": "oom"},
                }
            ]
        }
    }
    assert classify_failure(timeout).primary_category == "resource"
    assert (
        classify_failure(
            {"flow": {"steps": [{"name": "place", "state": "cancelled"}]}}
        ).primary_category
        == "cancelled"
    )
    assert (
        classify_failure(
            {
                "flow": {"steps": [{"name": "place", "state": "Success"}]},
                "signoffAssessment": {"status": "failed"},
            }
        ).primary_category
        == "design_constraint"
    )
    assert (
        classify_failure(
            {"flow": {"steps": [{"name": "place", "state": "Error"}]}}
        ).primary_category
        == "tool_failure"
    )


def test_design_tags_require_source_and_confidence_and_names_do_not_infer_structure():
    facts = {
        "workspaceSpec": {
            "design": {
                "name": "gcd",
                "tags": [
                    "datapath",
                    {"name": "memory", "source": "user", "confidence": "high"},
                    {"name": "invalid", "source": "folder", "confidence": "high"},
                ],
            }
        }
    }
    tags = design_tags(facts)
    assert [(item.name, item.source) for item in tags] == [
        ("datapath", "spec"),
        ("memory", "user"),
    ]
    assert memory_identity(facts) == {
        "memory_implementation": "unknown",
        "memory_bits": None,
        "macro_count": None,
    }
