"""Failed read-only checks may expose fresh evidence, never a successful final."""

import json
from pathlib import Path

CHECKS = {"lec", "postRouteLec", "lvs", "drc", "antennaCheck", "sta", "powerAnalysis", "emir"}


def require_evidence(step: str, directory: Path, results: dict) -> None:
    if step not in CHECKS or not results.get("analysis"):
        raise ValueError("EDA step failed without a replayable diagnostic")
    analysis = json.loads((directory / results["analysis"]).read_text())
    # Only a parsed, fresh, frozen native report counts as evidence. A generic
    # subprocess exit event or an empty unavailable index does not qualify.
    if not any(view.get("source") for view in analysis.get("views", [])):
        raise ValueError("EDA step failed without a current diagnostic report")
    results["diagnostic_only"] = True
