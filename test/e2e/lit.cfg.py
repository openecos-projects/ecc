# Lit config for real-design flow checks (checked-in).
#
# Test data (ecc.toml, rtl/, checks/*.check, *.lit) lives in an external
# designs directory; workspaces are produced beforehand by
# nix/scripts/run_designs.sh. This suite only checks, never runs flows:
# a design whose workspace is missing shows as UNSUPPORTED, not FAIL.
#
# Run: ECC_E2E_DESIGNS=<designs> ECC_FLOW_WORKSPACES=<out-root> \
#        bash nix/scripts/signoff_lit.sh test/e2e

import os
from pathlib import Path

import lit.formats

_ROOT = Path(__file__).resolve().parent
config.name = "ecc-flow-e2e"
config.test_format = lit.formats.ShTest(execute_external=True)
config.suffixes = [".lit"]

repo = os.environ.get("ECC_REPO_ROOT") or str(_ROOT.parents[1])
designs = os.environ.get("ECC_E2E_DESIGNS") or ""
flows = os.environ.get("ECC_FLOW_WORKSPACES") or ""

if not designs or not Path(designs).is_dir():
    raise SystemExit("ECC_E2E_DESIGNS must point at the designs directory")
config.test_source_root = designs
config.test_exec_root = str(_ROOT / "Output")

filecheck = os.environ.get("FILECHECK") or "filecheck"

config.environment["ECC_REPO_ROOT"] = repo
config.substitutions.append(("%filecheck", filecheck))
config.substitutions.append(("%jq", os.environ.get("JQ") or "jq"))

if flows:
    config.substitutions.append(("%flows", flows))
    for entry in sorted(Path(flows).iterdir()):
        if (entry / "default" / "home" / "flow.json").is_file():
            config.available_features.add(f"flow-{entry.name}")
