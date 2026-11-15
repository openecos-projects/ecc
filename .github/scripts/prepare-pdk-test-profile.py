#!/usr/bin/env python3
"""Copy declared resources into an isolated, explicitly synthetic EM test profile."""

import argparse
import json
import os
import shutil
from pathlib import Path


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("source", type=Path)
    parser.add_argument("destination", type=Path)
    parser.add_argument("--em-model", required=True, type=Path)
    args = parser.parse_args()
    source = args.source.resolve(strict=True)
    destination = args.destination.resolve()
    descriptor = json.loads((source / "ecc-pdk.json").read_text())
    destination.mkdir(parents=True, exist_ok=False)
    for resource in descriptor["resources"].values():
        relative = Path(resource["path"])
        if relative.is_absolute() or ".." in relative.parts:
            raise ValueError(f"resource escapes package: {relative}")
        original = (source / relative).resolve(strict=True)
        original.relative_to(source)
        output = destination / relative
        output.parent.mkdir(parents=True, exist_ok=True)
        if not output.exists():
            try:
                os.link(original, output)
            except OSError:
                shutil.copyfile(original, output)
    if not any(item["role"] == "em" for item in descriptor["resources"].values()):
        shutil.copyfile(args.em_model, destination / "synthetic-test-em.tech")
        descriptor["resources"]["test-em"] = {"path": "synthetic-test-em.tech", "role": "em"}
        descriptor["profile_revision"] += "-synthetic-em-test-only"
        print("WARNING: synthetic EM data is for flow testing, not foundry signoff.")
    (destination / "ecc-pdk.json").write_text(json.dumps(descriptor))


if __name__ == "__main__":
    main()
