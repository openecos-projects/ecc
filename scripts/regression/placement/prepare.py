"""Freeze inputs, current Python sources and a qualified native runtime."""

import copy
import json
import shlex
import shutil
import subprocess
from pathlib import Path

from .common import cases, digest, read, require, write


def freeze_runtime(batch: Path, qualified: Path, repo: Path):
    target = batch / "runtime"
    shutil.copytree(
        qualified / "runtime", target, ignore=shutil.ignore_patterns("__pycache__", "*.pyc")
    )
    native = [path for path in target.rglob("*") if path.is_file() and ".so" in path.name]
    native.append(target / "python-nix")
    require(
        all(
            digest(path) == digest(qualified / "runtime" / path.relative_to(target))
            for path in native
        ),
        "Copied native runtime differs from its qualified source",
    )
    shutil.rmtree(target / "chipcompiler")
    shutil.copytree(
        repo / "chipcompiler",
        target / "chipcompiler",
        ignore=shutil.ignore_patterns("thirdparty", "__pycache__", "*.pyc"),
    )
    source = repo / "chipcompiler/thirdparty/ecc-dreamplace/dreamplace"
    for path in (target / "dreamplace").rglob("*.py"):
        if path.name != "configure.py":
            path.unlink()
    for path in source.rglob("*.py"):
        if path.name == "configure.py" or "__pycache__" in path.parts:
            continue
        destination = target / "dreamplace" / path.relative_to(source)
        destination.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(path, destination)
    shutil.copy2(source / "params.json", target / "dreamplace/params.json")
    shutil.copytree(
        Path(__file__).parent,
        batch / "runner/scripts/regression/placement",
        ignore=shutil.ignore_patterns("__pycache__", "*.pyc"),
    )
    launcher = (qualified / "run_python.sh").read_text().replace(str(qualified), str(batch))
    runner = shlex.quote(str(batch / "runner") + ":")
    require("export PYTHONPATH=" in launcher, "Qualified launcher must define PYTHONPATH")
    launcher = launcher.replace("export PYTHONPATH=", "export PYTHONPATH=" + runner)
    (batch / "run_python.sh").write_text(launcher)
    shutil.copymode(qualified / "run_python.sh", batch / "run_python.sh")
    return {
        str(path.relative_to(target)): digest(path) for path in target.rglob("*") if path.is_file()
    }


def prepare(
    batch: Path,
    source: Path,
    qualified: Path,
    profile: Path,
    openroad: Path,
    selected: list[str] | None,
):
    repo = Path(__file__).resolve().parents[3]
    manifest = copy.deepcopy(cases(source))
    names = {case["name"] for case in manifest}
    require(len(names) == len(manifest), "Duplicate case names")
    if selected:
        require(set(selected) <= names, f"Unknown cases: {set(selected) - names}")
        manifest = [case for case in manifest if case["name"] in selected]
    require(bool(manifest), "No cases selected")
    policy = read(profile)
    require(
        policy["flow_kind"] == "placement" and policy["timing_opt_enabled"] == 1,
        "This runner requires a placement profile with timing_opt enabled",
    )
    require(not batch.exists(), f"Output already exists: {batch}")
    batch.mkdir(parents=True)
    shutil.copy2(profile, batch / "profile.json")
    snapshots = {}
    pdk_manifest = {}

    def snapshot_pdk(value):
        if value not in snapshots:
            original = Path(value)
            target = batch / "pdk" / f"{digest(original)[:16]}-{original.name}"
            target.parent.mkdir(exist_ok=True)
            shutil.copy2(original, target)
            snapshots[value] = str(target)
            pdk_manifest[str(target)] = {"source": value, "sha256": digest(target)}
        return snapshots[value]

    for case in manifest:
        name = case["name"]
        require(Path(name).name == name and name not in (".", ".."), f"Invalid case name: {name}")
        out = batch / "cases" / name
        out.mkdir(parents=True)
        project = read(source / "projects" / name / "project.json")
        origin = Path(project["workspaces"][-1]["workspace_path"])
        parameters = read(origin / "home/engineering-snapshot.json")["parameters"]
        write(out / "source-project.json", project)
        write(out / "source-parameters.json", parameters)
        case["source_input_paths"] = case["inputs"].copy()
        for kind, value in case["source_input_paths"].items():
            original = Path(value)
            require(digest(original) == case["hashes"][kind], f"Changed input: {name}/{kind}")
            target = batch / "inputs" / name / original.name
            target.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(original, target)
            case["inputs"][kind] = str(target)
        pdk = case["pdk"]
        pdk["tech"] = snapshot_pdk(pdk["tech"])
        for key in ("lefs", "libs"):
            pdk[key] = [snapshot_pdk(value) for value in pdk[key]]
        write(out / "case.json", case)
        write(out / "status.json", {"case": name, "status": "queued", "stage": "placement"})
    write(batch / "cases_manifest.json", {"source_batch": str(source), "cases": manifest})
    write(batch / "pdk_manifest.json", pdk_manifest)
    runtime_hashes = freeze_runtime(batch, qualified, repo)
    evaluators = ("evaluate_placement_rc.tcl", "evaluate_openroad_gr.tcl")
    for filename in evaluators:
        shutil.copy2(Path(__file__).parent / filename, batch / filename)
    write(
        batch / "provenance.json",
        {
            "source_batch": str(source),
            "runtime_copied_from": str(qualified / "runtime"),
            "python_source_repository": str(repo),
            "profile": policy,
            "profile_sha256": digest(batch / "profile.json"),
            "runtime_file_hashes": runtime_hashes,
            "launcher_sha256": digest(batch / "run_python.sh"),
            "runner_file_hashes": {
                str(path.relative_to(batch / "runner")): digest(path)
                for path in (batch / "runner").rglob("*")
                if path.is_file()
            },
            "openroad_binary": str(openroad),
            "openroad_sha256": digest(openroad),
            "evaluators": {filename: digest(batch / filename) for filename in evaluators},
        },
    )
    with (batch / "prepare.log").open("x") as stream:
        result = subprocess.run(
            [
                "bash",
                str(batch / "run_python.sh"),
                "-m",
                "scripts.regression.placement",
                "prepare-workspaces",
                "--batch",
                str(batch),
            ],
            cwd=batch,
            stdout=stream,
            stderr=subprocess.STDOUT,
        )
    (batch / "prepare.exit").write_text(str(result.returncode) + "\n")
    require(result.returncode == 0, f"Workspace preparation failed; see {batch / 'prepare.log'}")


def prepare_workspaces(batch: Path):
    from dreamplace.flows.flow_config import resolve_flow_config

    from chipcompiler.data.workspace import create_workspace
    from chipcompiler.project.api import create_project_manifest, mutate_project_manifest
    from chipcompiler.project.manifest_write import update_manifest
    from chipcompiler.tools.ecc_dreamplace.parameter_overrides import (
        apply_direct_config_overrides,
        apply_parameter_overrides,
    )

    profile = read(batch / "profile.json")
    for case in cases(batch):
        name = case["name"]
        out = batch / "cases" / name
        parameters = read(out / "source-parameters.json")
        parameters.pop("_flow", None)
        parameters.update(
            design=name,
            top_module=case["top"],
            clock=case["clock"],
            frequency_max=case["frequency_mhz"],
            cell_padding_x=profile["cell_padding_x"],
            target_density=profile["target_density"],
            target_overflow=profile["stop_overflow"],
            bottom_layer="MET2",
            top_layer="MET5",
            config_overrides={"dreamplace": profile},
        )
        project = batch / "projects" / name
        target = project / "placement"
        pdk = case["pdk"]
        result = create_workspace(
            target,
            case["inputs"]["def"],
            case["inputs"]["verilog"],
            pdk["name"],
            parameters,
            pdk_root=pdk["root"],
            pdk_overrides={
                key: value for key, value in pdk.items() if key not in ("name", "root", "version")
            },
            flow_config={"start_step": "place", "end_step": "place"},
            sdc=case["inputs"]["sdc"],
        )
        require(result is not None, f"Workspace creation failed: {name}")
        create_project_manifest(project, "placement-regression-" + name, name)
        original = read(out / "source-project.json")
        design = original["base_design"]
        design.update(
            origin_def=case["inputs"]["def"],
            netlist=case["inputs"]["verilog"],
            sdc=case["inputs"]["sdc"],
        )
        require(
            update_manifest(
                str(project), lambda doc, design=design: doc.update(base_design=design)
            ),
            name,
        )
        patch = original["workspaces"][-1]["parameter_patch"]
        patch.update(
            {
                key: {"from": None, "to": parameters[key]}
                for key in (
                    "cell_padding_x",
                    "target_density",
                    "target_overflow",
                    "config_overrides",
                )
            }
        )
        mutate_project_manifest(
            project,
            {
                "type": "register_workspace",
                "workspace_id": "placement",
                "name": name,
                "workspace_path": str(target),
                "parameter_patch": patch,
            },
        )
        cfg = read(target / "config/dreamplace_ecc.json")
        cfg = resolve_flow_config(
            apply_direct_config_overrides(apply_parameter_overrides(cfg, parameters), parameters),
            explicit_keys=set(profile),
        )
        require(
            json.loads(json.dumps({key: cfg[key] for key in profile})) == profile,
            f"Profile changed by resolver: {name}",
        )
        write(
            out / "preflight.json",
            {"status": "ok", "case": name, "parameters": {key: cfg[key] for key in profile}},
        )
        print("PREFLIGHT_OK", name, flush=True)
