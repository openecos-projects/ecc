"""Wait for the pinned native repository's CI, then download its wheel artifact."""

import argparse
import json
import subprocess
import time
from pathlib import Path


def api(path):
    result = subprocess.run(
        ["gh", "api", path], check=True, capture_output=True, text=True, timeout=120
    )
    return json.loads(result.stdout)


def wait_for_wheel(repo, commit, artifact, timeout=2700):
    deadline = time.monotonic() + timeout
    while True:
        runs = api(f"repos/{repo}/actions/workflows/ci.yml/runs?head_sha={commit}&per_page=100")[
            "workflow_runs"
        ]
        runs = [run for run in runs if run["head_sha"] == commit]
        for run in runs:
            if run["conclusion"] != "success":
                continue
            artifacts = api(f"repos/{repo}/actions/runs/{run['id']}/artifacts?per_page=100")
            if any(
                item["name"] == artifact and not item["expired"] and item["size_in_bytes"] > 0
                for item in artifacts["artifacts"]
            ):
                return run["id"]
        if not any(run["status"] != "completed" for run in runs):
            raise RuntimeError(
                f"No successful CI with usable {artifact} for {repo} at {commit}; "
                "build and validate this pinned submodule commit first."
            )
        remaining = deadline - time.monotonic()
        if remaining <= 0:
            raise TimeoutError(f"Timed out waiting for {repo} CI at {commit}")
        print(f"Waiting for {repo} CI at {commit} ({int(remaining)}s remaining)", flush=True)
        time.sleep(min(30, remaining))


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("repo")
    parser.add_argument("submodule")
    parser.add_argument("artifact")
    parser.add_argument("destination", type=Path)
    args = parser.parse_args()
    commit = subprocess.check_output(
        ["git", "rev-parse", f"HEAD:{args.submodule}"], text=True
    ).strip()
    run_id = wait_for_wheel(args.repo, commit, args.artifact)
    args.destination.mkdir(parents=True, exist_ok=True)
    print(f"Downloading {args.artifact} from {args.repo} run {run_id} ({commit})", flush=True)
    subprocess.run(
        [
            "gh",
            "run",
            "download",
            str(run_id),
            "--repo",
            args.repo,
            "--name",
            args.artifact,
            "--dir",
            str(args.destination),
        ],
        check=True,
        timeout=300,
    )


if __name__ == "__main__":
    main()
