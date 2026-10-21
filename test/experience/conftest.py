import hashlib
import json

import pytest

from chipcompiler.engine.snapshot import SNAPSHOT_SCHEMA_VERSION
from chipcompiler.engine.snapshot_qor import unavailable_qor_snapshot_extension


@pytest.fixture
def workspace_factory(tmp_path):
    def create(name="workspace", *, schema=SNAPSHOT_SCHEMA_VERSION):
        root = tmp_path / name
        home = root / "home"
        home.mkdir(parents=True)
        flow = {"steps": [{"name": "Synthesis", "tool": "yosys", "state": "Success"}]}
        (home / "flow.json").write_text(json.dumps(flow))
        (home / "checklist.json").write_text(
            json.dumps(
                {
                    "schema_version": 3,
                    "kind": "signoff_checklist",
                    "checklist": [],
                }
            )
        )
        report = root / "Synthesis_yosys" / "analysis" / "qor_metrics.json"
        report.parent.mkdir(parents=True)
        report.write_text(json.dumps({"metrics": [{"value": 12.5, "unit": "um^2"}]}))
        reference = str(report.relative_to(root))
        workspace_id = f"identity-{name}"
        artifact_id = (
            "artifact-" + hashlib.sha256(f"{workspace_id}\0{reference}".encode()).hexdigest()[:32]
        )
        snapshot = {
            "schemaVersion": schema,
            "workspaceId": workspace_id,
            "workspaceRevision": 1,
            "cause": "flow_step.success",
            "flow": flow,
            "parameters": {},
            "checklist": {},
            "signoffAssessment": {},
            "analysis": {},
            "qorAssessment": {"metrics": []},
            "metrics": [],
            "qorSnapshotExtension": unavailable_qor_snapshot_extension("no reports"),
            "timingPreview": {},
            "hotspotPreview": {},
            "workspaceSpec": {},
            "workspaceBindings": {},
            "stepOutputs": {"directory": ".", "design": "sample", "steps": []},
            "artifacts": [
                {
                    "artifactId": artifact_id,
                    "reference": reference,
                    "availability": "available",
                }
            ],
        }
        (home / "engineering-snapshot.json").write_text(json.dumps(snapshot))
        return root

    return create
