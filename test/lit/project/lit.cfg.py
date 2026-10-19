# Lit suite: project scenarios (CLI --project and RPC stdio).
#
# Run:
#   CHIPCOMPILER_ICS55_PDK_ROOT=... nix run .#signoff-lit -- test/lit/project
#   bash nix/scripts/ci_project_lit.sh

import os
from pathlib import Path

import lit.formats

_ROOT = Path(__file__).resolve().parent
config.name = "ecc-project-scenario"
config.test_format = lit.formats.ShTest(execute_external=True)
config.suffixes = [".lit"]
config.test_source_root = str(_ROOT / "cases")
config.test_exec_root = str(_ROOT / "Output")

repo = os.environ.get("ECC_REPO_ROOT") or str(_ROOT.parents[2])
python = os.environ.get("PYTHON") or "python3"
filecheck = os.environ.get("FILECHECK") or "FileCheck"
scripts = Path(repo) / "nix" / "scripts"
checks = _ROOT / "checks"

config.environment["ECC_REPO_ROOT"] = repo
config.environment["PYTHON"] = python
if os.environ.get("ECC"):
    config.environment["ECC"] = os.environ["ECC"]
if os.environ.get("CHIPCOMPILER_ICS55_PDK_ROOT"):
    config.environment["CHIPCOMPILER_ICS55_PDK_ROOT"] = os.environ[
        "CHIPCOMPILER_ICS55_PDK_ROOT"
    ]
    config.available_features.add("ics55-pdk")
if os.environ.get("CHIPCOMPILER_OSS_CAD_DIR") or os.environ.get("PATH"):
    # Propagate host tool PATH for yosys / ecc-tools children.
    config.environment["PATH"] = os.environ.get("PATH", "")
if os.environ.get("CHIPCOMPILER_OSS_CAD_DIR"):
    config.environment["CHIPCOMPILER_OSS_CAD_DIR"] = os.environ[
        "CHIPCOMPILER_OSS_CAD_DIR"
    ]
if os.environ.get("CHIPCOMPILER_ECC_SIZER_ROOT"):
    config.environment["CHIPCOMPILER_ECC_SIZER_ROOT"] = os.environ[
        "CHIPCOMPILER_ECC_SIZER_ROOT"
    ]
if os.environ.get("CHIPCOMPILER_KEPLER_FORMAL_ROOT"):
    config.environment["CHIPCOMPILER_KEPLER_FORMAL_ROOT"] = os.environ[
        "CHIPCOMPILER_KEPLER_FORMAL_ROOT"
    ]

config.environment["PYTHONPATH"] = os.pathsep.join(
    [repo] + ([os.environ["PYTHONPATH"]] if os.environ.get("PYTHONPATH") else [])
)

config.substitutions.extend(
    [
        ("%repo", repo),
        ("%python", python),
        ("%filecheck", filecheck),
        ("%cli_scenario", str(scripts / "run_cli_project_scenario.sh")),
        ("%rpc_scenario", str(scripts / "run_rpc_project_scenario.sh")),
        ("%check_status_success", str(checks / "status_success.check")),
    ]
)
