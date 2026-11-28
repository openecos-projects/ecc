#!/usr/bin/env python3
"""Build a compact recommended-frequency CSV from native final run results.

This is a consumer, not a signoff re-validator. Each input run supplies the
terminal status and coverage status produced by the normal signoff flow.
"""

import argparse
import csv
import json
import math
from dataclasses import dataclass
from decimal import Decimal, localcontext
from fractions import Fraction
from pathlib import Path


@dataclass(frozen=True)
class Candidate:
    frequency: Fraction
    mode: str
    vco: Fraction | None = None
    n: int | None = None
    select: int | None = None
    divider: int | None = None

    @property
    def od_code(self) -> str | None:
        if self.divider is None:
            return None
        return {1: "00", 2: "01", 4: "10", 8: "11"}.get(self.divider)


def _fraction(value: object, *, positive: bool = False) -> Fraction:
    if isinstance(value, bool) or not isinstance(value, (str, int, float)):
        raise ValueError("not a rational number")
    if isinstance(value, float) and not math.isfinite(value):
        raise ValueError("non-finite number")
    try:
        result = Fraction(str(value).strip())
    except (ValueError, ZeroDivisionError) as exc:
        raise ValueError("not a rational number") from exc
    if positive and result <= 0:
        raise ValueError("frequency must be positive")
    return result


def _display(value: Fraction | None) -> str:
    if value is None:
        return ""
    if value.denominator == 1:
        return str(value.numerator)
    with localcontext() as context:
        context.prec = 40
        text = format(Decimal(value.numerator) / Decimal(value.denominator), "f")
    return text.rstrip("0").rstrip(".")


def enumerate_candidates(refclk: Fraction, *, bypass: bool) -> list[Candidate]:
    """Enumerate legal configurations and deterministically deduplicate F_OUT."""
    if bypass:
        return [Candidate(refclk, "bypass")]
    by_output: dict[Fraction, Candidate] = {}
    for n in range(17, 256):
        for select in (0, 1):
            vco = refclk * n * (1 if select == 0 else 2)
            if not 500 <= vco <= 1200:
                continue
            for divider in (1, 2, 4, 8):
                candidate = Candidate(vco / divider, "pll", vco, n, select, divider)
                previous = by_output.get(candidate.frequency)
                key = (candidate.vco, candidate.n, candidate.divider, candidate.select)
                if previous is None or key < (
                    previous.vco,
                    previous.n,
                    previous.divider,
                    previous.select,
                ):
                    by_output[candidate.frequency] = candidate
    return sorted(by_output.values(), key=lambda item: item.frequency, reverse=True)


def _metric(payload: dict, metric_id: str) -> Fraction | None:
    metrics = payload.get("metrics")
    if not isinstance(metrics, list):
        return None
    matches = [item for item in metrics if isinstance(item, dict) and item.get("id") == metric_id]
    if len(matches) != 1:
        return None
    try:
        return _fraction(matches[0].get("value"), positive=True)
    except ValueError:
        return None


def _request(payload: dict, native_design: object) -> dict:
    if payload.get("schema_version") != 1 or payload.get("kind") != "frequency_run_results":
        raise ValueError("unsupported frequency input schema")
    if not isinstance(native_design, str) or payload.get("design") != native_design:
        raise ValueError("frequency design identity mismatch")
    base_id = payload.get("base_id")
    if not isinstance(base_id, str) or not base_id.strip():
        raise ValueError("frequency base_id is required")
    mode = payload.get("evidence_mode")
    if mode not in {"fixture", "signoff"}:
        raise ValueError("invalid frequency evidence_mode")
    params = payload.get("params")
    if not isinstance(params, dict):
        raise ValueError("frequency params must be an object")

    refclk = _fraction(params.get("pll_refclk_mhz"), positive=True)
    if not 5 <= refclk <= 40:
        raise ValueError("pll_refclk_mhz must be in [5, 40]")
    bypass = params.get("pll_bypass", False)
    if not isinstance(bypass, bool):
        raise ValueError("pll_bypass must be boolean")
    minimum = _fraction(params.get("frequency_min_mhz", 0))
    maximum = _fraction(params.get("frequency_max_mhz", 1200), positive=True)
    if minimum < 0 or maximum < minimum:
        raise ValueError("invalid candidate frequency range")

    ratio_raw = params.get("guardband_frequency_ratio")
    time_raw = params.get("guardband_time_ns")
    if ratio_raw is not None and time_raw is not None:
        raise ValueError("guardband ratio and time are mutually exclusive")
    ratio = _fraction(ratio_raw) if ratio_raw is not None else Fraction(0)
    guard_ns = _fraction(time_raw, positive=True) if time_raw is not None else None
    if not 0 <= ratio < 1:
        raise ValueError("guardband_frequency_ratio must be in [0, 1)")

    runs = payload.get("runs")
    if not isinstance(runs, list):
        raise ValueError("frequency runs must be an array")
    indexed = {}
    run_ids = set()
    for run in runs:
        if not isinstance(run, dict):
            raise ValueError("invalid frequency run")
        phase = run.get("phase")
        run_id = run.get("run_id")
        if phase not in {"verification", "guardband"}:
            raise ValueError("invalid frequency run phase")
        if not isinstance(run_id, str) or not run_id.strip() or run_id in run_ids:
            raise ValueError("frequency run_id must be non-empty and unique")
        if run.get("base_id") != base_id:
            raise ValueError("frequency run base_id mismatch")
        if run.get("status") not in {"pass", "fail", "unknown"}:
            raise ValueError("invalid frequency run status")
        if run.get("coverage_status") not in {"pass", "fail", "unknown"}:
            raise ValueError("invalid frequency coverage status")
        candidate = _fraction(run.get("candidate_mhz"), positive=True)
        key = (phase, candidate)
        if key in indexed:
            raise ValueError("duplicate frequency phase/candidate run")
        indexed[key] = run
        run_ids.add(run_id)

    return {
        "base_id": base_id,
        "evidence_mode": mode,
        "refclk": refclk,
        "bypass": bypass,
        "minimum": minimum,
        "maximum": maximum,
        "ratio": ratio,
        "guard_ns": guard_ns,
        "runs": indexed,
    }


def _scan(candidates: list[Candidate], runs: dict, phase: str) -> tuple[Candidate | None, str, str]:
    """Return the highest pass; an unknown higher result blocks promotion."""
    for candidate in candidates:
        run = runs.get((phase, candidate.frequency))
        if run is None:
            return None, "unknown", ""
        status = run["status"]
        coverage = run["coverage_status"]
        if status == "pass" and coverage == "pass":
            return candidate, "pass", run["run_id"]
        if status == "unknown" or coverage == "unknown":
            return None, "unknown", ""
        # A completed failing run is negative evidence, even when a gate or
        # coverage check is the reason for that failure. Continue descending.
    return None, "exhausted", ""


def _row(kind, metric, value="", unit="", status="unavailable", detail="", run_id="", mode=""):
    return {
        "kind": kind,
        "metric": metric,
        "value": value,
        "unit": unit,
        "status": status,
        "detail": detail,
        "run_id": run_id,
        "evidence_mode": mode,
    }


def build_rows(sta: dict, request: dict | None = None, error: str = "") -> list[dict]:
    target = _metric(sta, "sta_target_frequency_mhz")
    achieved = _metric(sta, "sta_frequency_mhz")
    mode = request["evidence_mode"] if request is not None else ""
    rows = [
        _row(
            "frequency",
            "target_frequency_mhz",
            _display(target),
            "MHz",
            "pass" if target is not None else "unavailable",
            "" if target is not None else "native_target_unavailable",
            mode=mode,
        ),
        _row(
            "frequency",
            "achieved_fmax_mhz",
            _display(achieved),
            "MHz",
            "pass" if achieved is not None else "unavailable",
            "" if achieved is not None else "native_fmax_unavailable",
            mode=mode,
        ),
    ]

    verified = recommended = output = None
    verified_run = recommended_run = ""
    verified_status = recommended_status = "unavailable"
    verified_detail = recommended_detail = error or "not_evaluated"
    guard_limit = None
    if error or request is None:
        pass
    elif target is None:
        verified_detail = recommended_detail = "target_unavailable"
    else:
        upper = min(target, request["maximum"])
        candidates = [
            item
            for item in enumerate_candidates(request["refclk"], bypass=request["bypass"])
            if request["minimum"] <= item.frequency <= upper
        ]
        verified, scan_status, verified_run = _scan(candidates, request["runs"], "verification")
        if scan_status == "pass" and verified is not None:
            verified_status = "pass"
            verified_detail = ""
            output = verified
            if request["guard_ns"] is not None:
                guard_limit = Fraction(1000) / (
                    Fraction(1000) / verified.frequency + request["guard_ns"]
                )
            else:
                guard_limit = (1 - request["ratio"]) * verified.frequency
            guard_candidates = [item for item in candidates if item.frequency <= guard_limit]
            recommended, guard_status, recommended_run = _scan(
                guard_candidates, request["runs"], "guardband"
            )
            if guard_status == "pass":
                recommended_status = "pass"
                recommended_detail = ""
                output = recommended
            elif guard_status == "unknown":
                recommended_status = "incomplete_evidence"
                recommended_detail = "guardband_higher_unknown"
                recommended_run = ""
            else:
                recommended_status = "fail"
                recommended_detail = "guardband_exhausted"
        elif scan_status == "unknown":
            verified_status = recommended_status = "incomplete_evidence"
            verified_detail = "higher_candidate_unknown"
            recommended_detail = "higher_candidate_unknown"
        else:
            verified_status = recommended_status = "fail"
            verified_detail = "no_legal_candidate" if not candidates else "all_candidates_exhausted"
            recommended_detail = "no_verified_candidate"

    if recommended_status == "pass" and request is not None:
        if request["guard_ns"] is not None:
            recommended_detail = f"time_guard_ns={_display(request['guard_ns'])}"
        else:
            recommended_detail = f"g_f={_display(request['ratio'])}"
    rows.extend(
        [
            _row(
                "frequency",
                "pll_output_frequency_mhz",
                _display(output.frequency if output is not None else None),
                "MHz",
                "pass" if output is not None else "unavailable",
                "" if output is not None else recommended_detail,
                recommended_run or verified_run,
                mode,
            ),
            _row(
                "frequency",
                "verified_frequency_mhz",
                _display(verified.frequency if verified is not None else None),
                "MHz",
                verified_status,
                verified_detail,
                verified_run,
                mode,
            ),
            _row(
                "frequency",
                "guard_limit_mhz",
                _display(guard_limit),
                "MHz",
                "pass" if guard_limit is not None else "unavailable",
                "" if guard_limit is not None else recommended_detail,
                mode=mode,
            ),
            _row(
                "frequency",
                "recommended_frequency_mhz",
                _display(recommended.frequency if recommended is not None else None),
                "MHz",
                recommended_status,
                recommended_detail,
                recommended_run,
                mode,
            ),
        ]
    )

    if request is None:
        rows.extend(
            [
                _row("pll", "refclk_mhz", unit="MHz", detail=error),
                _row("pll", "mode", detail=error),
                _row("identity", "base_id", detail=error),
                _row("identity", "evidence_mode", detail=error),
            ]
        )
        return rows

    rows.extend(
        [
            _row(
                "pll",
                "refclk_mhz",
                _display(request["refclk"]),
                "MHz",
                "pass",
                mode=mode,
            ),
            _row("pll", "mode", "bypass" if request["bypass"] else "pll", status="pass", mode=mode),
        ]
    )
    if output is not None and output.mode == "pll":
        pll_rows = [
            ("n", str(output.n), "count"),
            ("select", str(output.select), "count"),
            ("od_code", output.od_code, ""),
            ("output_divider", str(output.divider), "count"),
            ("vco_mhz", _display(output.vco), "MHz"),
        ]
        rows.extend(
            _row(
                "pll", name, value, unit, "pass", run_id=recommended_run or verified_run, mode=mode
            )
            for name, value, unit in pll_rows
        )
    else:
        detail = "bypass_mode" if output is not None else recommended_detail
        rows.extend(
            _row("pll", name, detail=detail, mode=mode)
            for name in ("n", "select", "od_code", "output_divider", "vco_mhz")
        )
    rows.extend(
        [
            _row(
                "guardband",
                "frequency_domain_ratio",
                _display(request["ratio"]) if request["guard_ns"] is None else "",
                "ratio" if request["guard_ns"] is None else "",
                "pass" if request["guard_ns"] is None else "unavailable",
                "" if request["guard_ns"] is None else "time_domain_policy",
                mode=mode,
            ),
            _row(
                "guardband",
                "time_domain_ns",
                _display(request["guard_ns"]),
                "ns" if request["guard_ns"] is not None else "",
                "pass" if request["guard_ns"] is not None else "unavailable",
                "" if request["guard_ns"] is not None else "frequency_domain_policy",
                mode=mode,
            ),
            _row("identity", "base_id", request["base_id"], status="pass", mode=mode),
            _row("identity", "evidence_mode", mode, status="pass", mode=mode),
        ]
    )
    return rows


def _read_json(path: Path) -> dict:
    with path.open(encoding="utf-8") as stream:
        payload = json.load(stream)
    if not isinstance(payload, dict):
        raise ValueError("JSON root must be an object")
    return payload


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--input", type=Path, required=True)
    parser.add_argument("--sta-metrics", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()

    try:
        sta = _read_json(args.sta_metrics)
    except (OSError, ValueError, json.JSONDecodeError):
        sta = {}
    try:
        raw_request = _read_json(args.input)
        request = _request(raw_request, sta.get("design"))
        rows = build_rows(sta, request)
    except FileNotFoundError:
        rows = build_rows(sta, error="frequency_input_missing")
    except (OSError, ValueError, json.JSONDecodeError):
        rows = build_rows(sta, error="invalid_frequency_input")

    args.output.parent.mkdir(parents=True, exist_ok=True)
    with args.output.open("w", encoding="utf-8", newline="") as stream:
        writer = csv.DictWriter(
            stream,
            fieldnames=(
                "kind",
                "metric",
                "value",
                "unit",
                "status",
                "detail",
                "run_id",
                "evidence_mode",
            ),
            lineterminator="\n",
        )
        writer.writeheader()
        writer.writerows(rows)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
