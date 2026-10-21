"""Evaluate an unchanged final DEF with placement RC and GR50 parasitics."""

import os
import re
import subprocess
import time
from dataclasses import dataclass
from pathlib import Path

from .common import digest, read, require, write


@dataclass(frozen=True)
class Evaluation:
    script: str
    prefix: str
    rc: str
    marker: str


EVALUATIONS = {
    "external-placement": Evaluation(
        "evaluate_placement_rc.tcl",
        "PLACEMENT",
        "placement_MET2",
        "OPENROAD_PLACEMENT_AUDIT_END design_unchanged=1 clock=ideal rc=placement",
    ),
    "external-gr50": Evaluation(
        "evaluate_openroad_gr.tcl",
        "GR",
        "GR50_MET2_MET5",
        "OPENROAD_GR_AUDIT_END design_unchanged=1 clock=ideal rc=global_routing",
    ),
}


def tcl_string(value: str):
    for char in ("\\", '"', "$", "[", "]"):
        value = value.replace(char, "\\" + char)
    return '"' + value + '"'


def parse_metrics(text: str, prefix: str):
    timing = {
        key: float(re.findall(rf"^{key} max ([-0-9.]+)$", text, re.M)[-1]) for key in ("wns", "tns")
    }
    checks = {
        key: float(value)
        for key, value in re.findall(rf"^{prefix}_AUDIT_METRIC (\w+)=([-0-9.eE+]+)$", text, re.M)
    }
    return timing, checks


def evaluate(batch: Path, case: dict, stage: str, definition: Path, netlist: Path):
    specification = EVALUATIONS[stage]
    provenance = read(batch / "provenance.json")
    out = batch / "cases" / case["name"] / stage
    out.mkdir()
    pdk = case["pdk"]
    inputs = out / "inputs.tcl"
    bindings = {
        "tech_lef": tcl_string(pdk["tech"]),
        "cell_lefs": "[list " + " ".join(map(tcl_string, pdk["lefs"])) + "]",
        "liberties": "[list " + " ".join(map(tcl_string, pdk["libs"])) + "]",
        "input_sdc": tcl_string(case["inputs"]["sdc"]),
        "input_def": tcl_string(str(definition)),
    }
    inputs.write_text("".join(f"set {key} {value}\n" for key, value in bindings.items()))
    binary = Path(provenance["openroad_binary"])
    require(digest(binary) == provenance["openroad_sha256"], "OpenROAD binary changed")
    require(
        digest(batch / specification.script) == provenance["evaluators"][specification.script],
        "External evaluator changed",
    )
    environment = dict(os.environ, GR_AUDIT_INPUTS=str(inputs))
    for key in ("LD_LIBRARY_PATH", "TCL_LIBRARY", "PYTHONHOME", "PYTHONPATH"):
        environment.pop(key, None)
    before = (digest(definition), digest(netlist))
    started = time.perf_counter()
    with (out / "evaluate.log").open("x") as stream:
        proc = subprocess.run(
            [str(binary), "-exit", str(batch / specification.script)],
            cwd=out,
            env=environment,
            stdout=stream,
            stderr=subprocess.STDOUT,
        )
    (out / "evaluate.exit").write_text(str(proc.returncode) + "\n")
    require(proc.returncode == 0, f"External evaluation failed: {case['name']}/{stage}")
    text = (out / "evaluate.log").read_text()
    require(specification.marker in text, f"Missing terminal evaluation marker: {stage}")
    require((digest(definition), digest(netlist)) == before, "Evaluation changed its input files")
    timing, metrics = parse_metrics(text, specification.prefix)
    report = {
        "status": "completed",
        "case": case["name"],
        "timing_ns": timing,
        "electrical_checks": metrics,
        "clock": "ideal",
        "corner": "TT",
        "rc": specification.rc,
        "design_unchanged": True,
        "source_def": str(definition),
        "source_def_sha256": before[0],
        "elapsed_seconds": time.perf_counter() - started,
        "binary_sha256": digest(binary),
        "evaluator_sha256": digest(batch / specification.script),
    }
    write(out / "report.json", report)
    return report
