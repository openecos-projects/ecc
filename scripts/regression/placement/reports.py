"""Collect completed and partial measurements without filling missing results."""

import csv
import io
import json
import re
from pathlib import Path

from .common import cases, read, workspace, write, write_text


def collect(batch: Path):
    rows, counts = [], dict.fromkeys(("completed", "failed", "running", "queued"), 0)
    for case in cases(batch):
        name = case["name"]
        out = batch / "cases" / name
        state = read(out / "status.json")
        counts[state["status"]] += 1
        report_path = out / "report.json"
        if not report_path.exists():
            report_path = out / "placement-report.json"
        data = read(report_path) if report_path.exists() else {}
        placement = data.get("external_placement", {}).get("timing_ns", {})
        gr = data.get("external_gr50", {}).get("timing_ns", {})
        checks = data.get("external_gr50", {}).get("electrical_checks", {})
        rows.append(
            {
                "case": name,
                "status": state["status"],
                "stage": state["stage"],
                "gp_wns_ns": data.get("gp_ns", {}).get("wns"),
                "gp_tns_ns": data.get("gp_ns", {}).get("tns"),
                "internal_wns_ns": data.get("internal_ns", {}).get("wns"),
                "internal_tns_ns": data.get("internal_ns", {}).get("tns"),
                "external_placement_wns_ns": placement.get("wns"),
                "external_placement_tns_ns": placement.get("tns"),
                "external_gr50_wns_ns": gr.get("wns"),
                "external_gr50_tns_ns": gr.get("tns"),
                "gr50_slew_violation_count": checks.get("slew_violation_count"),
                "gr50_cap_violation_count": checks.get("cap_violation_count"),
                "gr50_worst_slew_slack_ns": checks.get("worst_slew_slack_ns"),
                "gr50_worst_cap_slack_pf": checks.get("worst_cap_slack_pf"),
                "iterations": data.get("iterations"),
                "final_overflow": data.get("final_overflow"),
                "gp_alpha": data.get("grad_balance", {}).get("weight_applied"),
                "sizing_window_count": len(data["sizing_windows"])
                if "sizing_windows" in data
                else None,
                "placement_elapsed_seconds": data.get("placement_elapsed_seconds"),
                "total_elapsed_seconds": data.get("elapsed_seconds"),
                "def": data.get("def"),
                "error": state.get("error"),
            }
        )
    profile = read(batch / "provenance.json")["profile"]
    summary = {
        "scope": "placement; external TT ideal-clock placement RC and GR50 STA",
        "profile": profile,
        "counts": counts,
        "rows": rows,
    }
    write(batch / "results.json", summary)
    write(batch / "batch-status.json", counts)
    stream = io.StringIO()
    writer = csv.DictWriter(stream, fieldnames=list(rows[0]))
    writer.writeheader()
    writer.writerows(rows)
    write_text(batch / "results.csv", stream.getvalue())
    fields = (
        "overflow_reference_mode",
        "timing_placement_carrier",
        "timing_opt_sizing_rounds",
        "timing_opt_buffering_enabled",
        "timing_opt_coefficients",
        "timing_coeff_growth_factor",
        "timing_grad_balance_target_ratio",
        "timing_aggregation_mode",
        "timing_aggregation_tau_ps",
        "cell_padding_x",
        "target_density",
    )
    lines = [
        f"Placement regression: {len(rows)} cases.",
        "",
        "Configuration: " + json.dumps({key: profile[key] for key in fields}),
        "",
        "Timing units: ns. External TT, ideal clocks; placement MET2 RC or GR50 MET2-MET5, "
        "capacity adjustment 0.5; no repair.",
        "",
        "| Case | Final placement internal WNS / TNS | External placement RC WNS / TNS | "
        "External GR50 WNS / TNS | Status |",
        "|---|---:|---:|---:|---|",
    ]
    for row in rows:
        pairs = []
        for prefix in ("internal", "external_placement", "external_gr50"):
            a, b = row[prefix + "_wns_ns"], row[prefix + "_tns_ns"]
            pairs.append("—" if a is None or b is None else f"{a:.3f} / {b:.3f}")
        lines.append(
            "| " + " | ".join([row["case"], *pairs, f"{row['status']}: {row['stage']}"]) + " |"
        )
    for headings, columns in (
        (
            ("GP iterations", "Final overflow", "GP alpha", "Sizing windows", "Placement seconds"),
            (
                ("iterations", 0),
                ("final_overflow", 6),
                ("gp_alpha", 3),
                ("sizing_window_count", 0),
                ("placement_elapsed_seconds", 1),
            ),
        ),
        (
            ("GR50 slew count", "GR50 cap count", "Worst slew slack ns", "Worst cap slack pF"),
            (
                ("gr50_slew_violation_count", 0),
                ("gr50_cap_violation_count", 0),
                ("gr50_worst_slew_slack_ns", 3),
                ("gr50_worst_cap_slack_pf", 6),
            ),
        ),
    ):
        lines.extend(
            ["", "| Case | " + " | ".join(headings) + " |", "|---|" + "---:|" * len(columns)]
        )
        for row in rows:
            values = [
                "—" if row[key] is None else f"{row[key]:.{digits}f}" for key, digits in columns
            ]
            lines.append("| " + " | ".join([row["case"], *values]) + " |")
    write_text(batch / "results.md", "\n".join(lines) + "\n")
    return summary


def status(batch: Path):
    summary = collect(batch)
    for row in summary["rows"]:
        if row["status"] != "running":
            continue
        log = workspace(batch, row["case"]) / "place_dreamplace/log/place.log"
        if log.exists():
            with log.open("rb") as stream:
                stream.seek(max(0, log.stat().st_size - 65536))
                text = stream.read().decode(errors="replace")
            iterations = re.findall(r"iteration\s+(\d+),", text, re.I)
            row["last_logged_iteration"] = int(iterations[-1]) if iterations else None
    return {
        "counts": summary["counts"],
        "cases": summary["rows"],
        "table": str(batch / "results.md"),
    }
