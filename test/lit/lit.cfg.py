# Lit config for ecc signoff CSV gates (checked-in).
#
# Run: see README.md in this directory.
# Or: bash nix/scripts/signoff_lit.sh

import os
from pathlib import Path

import lit.formats

_ROOT = Path(__file__).resolve().parent
config.name = "ecc-signoff-csv"
config.test_format = lit.formats.ShTest(execute_external=True)
config.suffixes = [".lit"]
config.test_source_root = str(_ROOT / "cases")
config.test_exec_root = str(_ROOT / "Output")

repo = os.environ.get("ECC_REPO_ROOT") or str(_ROOT.parents[1])
python = os.environ.get("PYTHON") or "python3"
filecheck = os.environ.get("FILECHECK") or "filecheck"
scripts = Path(repo) / "nix" / "scripts"
export_csv = os.environ.get("ECC_EXPORT_SIGNOFF_CSV") or str(scripts / "export_signoff_csv.sh")
materialize = os.environ.get("ECC_MATERIALIZE_READY") or str(scripts / "materialize_signoff_workspace.sh")
spec = os.environ.get("ECC_SIGNOFF_CSV_SPEC") or str(_ROOT / "profiles" / "signoff.yml")
workspace = os.environ.get("ECC_TEST_WORKSPACE") or ""
profiles = _ROOT / "profiles"

config.environment["ECC_REPO_ROOT"] = repo
config.environment["PYTHON"] = python
_lit_path = str(_ROOT)
_existing = os.environ.get("PYTHONPATH", "")
config.environment["PYTHONPATH"] = os.pathsep.join(
    [repo, _lit_path] + ([_existing] if _existing else [])
)
if workspace:
    config.environment["ECC_TEST_WORKSPACE"] = workspace
    config.available_features.add("packaged-workspace")

config.substitutions.extend(
    [
        ("%repo", repo),
        ("%python", python),
        ("%filecheck", filecheck),
        ("%export_csv", export_csv),
        ("%materialize", materialize),
        ("%spec", spec),
        # Avoid %check* names — lit/FileCheck may leave them unsubstituted.
        ("%gatefile_pass", str(profiles / "signoff_gates.check")),
        ("%gatefile_metric_fail", str(profiles / "signoff_gates_metric_fail.check")),
        ("%gatefile_checklist_blocked", str(profiles / "signoff_gates_checklist_blocked.check")),
        ("%gatefile_missing_metric", str(profiles / "signoff_gates_missing_metric.check")),
        ("%workspace", workspace),
    ]
)
