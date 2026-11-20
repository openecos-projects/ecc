"""Apply reviewed ICS55 9T defaults through the public ECC configuration CLI.

Run against an existing, complete ECC adaptation. PDK resources and existing
project locks are never rewritten. Use an isolated ECC_PDK_INVENTORY for tests.
"""

import argparse
import hashlib
import json
import subprocess
from pathlib import Path


def configure(ecc: str, root: Path, *, synthetic_emir: bool = False) -> dict:
    def command(*arguments: str) -> dict:
        result = subprocess.run(
            [ecc, "pdk", "configure", *arguments, "--root", str(root)],
            check=True,
            capture_output=True,
            text=True,
        )
        return json.loads(result.stdout)

    current = command("show")
    descriptor = current["descriptor"]
    if (
        descriptor["family_id"] != "ics55"
        or not descriptor["release"].startswith("v2")
        or descriptor["cells"]["site_core"] != "SC9T_site"
    ):
        raise ValueError("This update requires the ICS55 v2 SC9T_site adaptation; not ICS55 7T.")

    # These are ECC policies. The 0.30 um rail covers the V2 filler VDD/VSS
    # rectangles (-0.15..0.15 and 1.65..1.95 um) before signal routing.
    parameters = descriptor["parameters"]
    parameters["bottom_layer"] = "MET1"
    # Coarse GR timing must use its qualified MET2-MET5 range independently
    # of detailed routing's MET1 pin access. Explicit CLI overrides still win.
    parameters.setdefault("dreamplace", {})["gpugr_bottom_routing_layer"] = "MET2"
    cells = descriptor["cells"]
    cells["fillers"] = [f"FILL{width}_9TSVT" for width in (32, 16, 8, 4, 2, 1)]
    tools = descriptor["tools"]
    configs = tools["configs"]
    configs["Floorplan"]["pdn_generator"]["rail"] = [
        {"routing_layer_name": "MET1", "width_micron": 0.30}
    ]
    configs["filler"]["MJ"] = {"-filler": ""}  # Resolve cells.fillers, never all CORE cells.
    if synthetic_emir:
        configs["emir"]["synthetic_model"] = "ics55"

    resources = descriptor["resources"]
    declared = {resource["path"] for resource in resources.values()}
    for path in sorted(root.rglob("*.gds")):
        relative = path.relative_to(root).as_posix()
        if relative in declared or not path.is_file():
            continue
        if not path.resolve().is_relative_to(root.resolve()):
            raise ValueError(f"GDS resource escapes the selected PDK: {relative}")
        with path.open("rb") as stream:
            digest = hashlib.file_digest(stream, "sha256").hexdigest()
        key = "gds-" + hashlib.sha256(relative.encode()).hexdigest()[:16]
        resources[key] = {"path": relative, "role": "gds", "sha256": digest}

    # One revision-checked CLI transaction per owned section. Run only with no
    # concurrent configuration editor; a conflict fails instead of overwriting it.
    revision = current["revision"]
    for field, value in (
        ("resources", resources),
        ("parameters", parameters),
        ("cells", cells),
        ("tools", tools),
        ("profile_revision", "ics55-v2-9t-20261118"),
    ):
        updated = command(
            "set",
            "--field",
            field,
            "--value-json",
            json.dumps(value),
            "--expected-revision",
            revision,
        )
        revision = updated["revision"]
    return command("show")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--ecc", required=True, help="Explicit path to the locally built ECC CLI")
    parser.add_argument("--root", required=True, type=Path)
    parser.add_argument(
        "--synthetic-emir", action="store_true", help="Flow test only, NOT FOR SIGNOFF"
    )
    arguments = parser.parse_args()
    print(
        json.dumps(
            configure(arguments.ecc, arguments.root, synthetic_emir=arguments.synthetic_emir),
            indent=2,
        )
    )
