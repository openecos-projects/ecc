"""ECC-QoR draft 3 analysis engine.

Single source of truth for QoR scoring: build a workspace-level
analysis from the per-step analysis artifacts, emit the versioned
``home/qor_report.json`` contract, and render the CLI text report.
The GUI is a renderer of this report, not a second scorer.
"""

from datetime import UTC, datetime
from pathlib import Path

from chipcompiler.analysis.qor import schema as qor_schema
from chipcompiler.analysis.qor.diagnosis import build_diagnoses
from chipcompiler.analysis.qor.dimensions import evaluate_dimensions
from chipcompiler.analysis.qor.evidence import evaluate_evidence
from chipcompiler.analysis.qor.feasibility import evaluate_feasibility
from chipcompiler.analysis.qor.features import compute_features
from chipcompiler.analysis.qor.loader import load_workspace_qor_inputs
from chipcompiler.analysis.qor.models import (
    SCHEMA_VERSION,
    SCORING_ENGINE,
    InflationView,
    PowerObservation,
    QorAnalysis,
)
from chipcompiler.analysis.qor.scoring import evaluate_scalar_summary
from chipcompiler.utility.json import json_write

REPORT_FILENAME = "qor_report.json"


def build_qor_analysis(workspace) -> QorAnalysis:
    """Analyze one workspace's current analysis outputs (spec §14.2 facade)."""
    inputs = load_workspace_qor_inputs(workspace)
    bundle = compute_features(inputs)
    dimensions = evaluate_dimensions(bundle, inputs)
    feasibility = evaluate_feasibility(inputs)
    evidence = evaluate_evidence(inputs, bundle)
    scalar = evaluate_scalar_summary(feasibility, dimensions, inputs.profile)
    diagnoses = build_diagnoses(feasibility, dimensions, bundle, inputs)

    return QorAnalysis(
        schema_version=SCHEMA_VERSION,
        scoring_engine=SCORING_ENGINE,
        design=inputs.design,
        workspace=inputs.workspace_path,
        timestamp=datetime.now(UTC).isoformat(),
        profile=inputs.profile,
        tclk_ns=inputs.tclk_ns,
        feasibility=feasibility,
        evidence=evidence,
        qor_record=dimensions,
        scalar_summary=scalar,
        diagnoses=diagnoses,
        inflation=InflationView(
            i_place=bundle.i_place,
            i_route=bundle.i_route,
            i_total=bundle.i_total,
            congestion_severity=bundle.congestion_severity,
            compatibility_status=(
                bundle.compatibility.status if bundle.compatibility else "INCOMPATIBLE"
            ),
        ),
        power=PowerObservation(
            total_uw=inputs.power_total_uw,
            budget_uw=inputs.power_budget_uw,
            source_path=inputs.power_source_path,
            source_kind=inputs.power_source_kind,
            corner=inputs.power_corner,
        ),
        flow_steps=dict(inputs.flow_states),
        config_warnings=list(inputs.config_warnings),
    )


def report_path(workspace) -> Path:
    return Path(workspace.directory or "") / "home" / REPORT_FILENAME


def write_qor_report(workspace, analysis=None) -> Path:
    """Persist the versioned report consumed by ECOS Studio (hard cut)."""
    analysis = analysis if analysis is not None else build_qor_analysis(workspace)
    payload = analysis.to_dict()
    violations = qor_schema.validate_report(payload)
    if violations:
        raise ValueError(f"qor report failed schema validation: {violations}")
    destination = report_path(workspace)
    if not json_write(file_path=destination, data=payload):
        raise OSError(f"failed to write qor report: {destination}")
    return destination


def refresh_workspace_qor_report(workspace) -> Path:
    """Post-step hook entry point; callers own exception handling."""
    return write_qor_report(workspace)


def render_qor_analysis(analysis, inputs=None) -> str:
    from chipcompiler.analysis.qor.renderer import render

    return render(analysis, inputs)


__all__ = [
    "build_qor_analysis",
    "render_qor_analysis",
    "refresh_workspace_qor_report",
    "report_path",
    "write_qor_report",
]
