"""Workspace-level QoR report entry points.

The scoring implementation lives in ``chipcompiler.analysis.qor``
(ECC-QoR draft 3); this module is the engine-side facade the CLI uses.
``home/qor_report.json`` is written by the flow engine after each
successful step via ``analysis.qor.refresh_workspace_qor_report``.
"""

from chipcompiler.analysis.qor import (
    build_qor_analysis,
    render_qor_analysis,
)
from chipcompiler.analysis.qor.loader import load_workspace_qor_inputs

__all__ = ["build_qor_report", "generate_qor_report"]


def build_qor_report(workspace):
    """Score one workspace's current analysis outputs (QorAnalysis)."""
    return build_qor_analysis(workspace)


def generate_qor_report(workspace, report=None) -> str:
    """Render the workspace QoR text report.

    Pass a prebuilt *report* to render the exact snapshot the caller
    already collected instead of re-traversing the workspace.
    """
    report = report if report is not None else build_qor_report(workspace)
    return render_qor_analysis(report, load_workspace_qor_inputs(workspace))
