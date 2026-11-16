"""Validate stable tool samples and publish indexed replay deltas."""

import json
import shutil
from pathlib import Path

from chipcompiler.tools.replay_storage import atomic_json, read_pointer, update_pointer

REPORT_ONLY = {"Synthesis", "lec", "postRouteLec"}
UNCHANGED_LAYOUT = {"Harden", "powerAnalysis", "emir", "RCX", "sta", "antennaCheck", "lvs", "drc"}


def publish(
    root: Path,
    attempt: str,
    step: str,
    tool: str,
    duration_ns: int,
    *,
    results: dict | None = None,
    started_unix_ns: int = 0,
    defer_completion: bool = False,
) -> None:
    """Convert real tool samples to reversible semantic diffs and seek checkpoints."""
    directory = root / "attempts" / attempt
    if (directory / "capture" / "error.json").exists():
        raise ValueError("native Replay capture failed; see tool log")
    from chipcompiler.tools.replay_delta import translations, write_frame
    from chipcompiler.tools.replay_logic import collect_logical

    collect_logical(directory)
    samples = []
    for path in (directory / "capture").glob("*.json"):
        sample = json.loads(path.read_text())
        samples.append((sample["elapsed_ns"], sample["sequence"], path, sample["state_domain"]))
    samples.sort(key=lambda entry: (entry[0], entry[1], entry[2].name))
    capture_dir = directory / "capture"
    if not samples and step in REPORT_ONLY:
        timing_path = capture_dir / "subflows.jsonl"
        events = (
            [json.loads(line) for line in timing_path.read_text().splitlines()]
            if timing_path.exists()
            else []
        )
        if not events:
            events = [{"name": "analysis", "state": "Success", "elapsed_ns": duration_ns}]
        for sequence, event in enumerate(events):
            final = sequence == len(events) - 1
            path = capture_dir / f"report-{sequence:06d}.json"
            state_domain = "analysis_complete" if final else "analysis_state"
            atomic_json(
                path,
                {
                    "sequence": sequence,
                    "elapsed_ns": event["elapsed_ns"],
                    "phase": "analysis_complete" if final else "analysis_progress",
                    "subflow": event["name"],
                    "state_domain": state_domain,
                    "objects": {},
                },
            )
            samples.append((event["elapsed_ns"], sequence, path, state_domain))
    inputs = [sample for sample in samples if sample[3] == "native_input"]
    if (
        inputs
        and step in UNCHANGED_LAYOUT
        and samples[-1][3] not in {"native_committed", "analysis_complete"}
    ):
        elapsed_ns, sequence, source, _ = inputs[0]
        sample = json.loads(source.read_text())
        sample.update(
            sequence=sequence + 1,
            elapsed_ns=max(elapsed_ns, duration_ns),
            phase="analysis_complete",
            subflow="analysis",
            state_domain="analysis_complete"
            if (results or {}).get("diagnostic_only")
            else "native_committed",
        )
        path = capture_dir / "native-analysis-final.json"
        atomic_json(path, sample)
        samples.append((sample["elapsed_ns"], sequence + 1, path, "native_committed"))
    if not samples or samples[-1][3] not in {"native_committed", "analysis_complete"}:
        raise ValueError("tool did not provide a committed final Replay sample")
    objects, touched, frames, subflows = {}, set(), [], []
    baseline, deleted = {}, {}
    changes_by_kind = {}
    from chipcompiler.tools.replay_identity import Identities

    identities = Identities()
    checkpoint_bytes, chain_bytes, chain_frames = 0, 0, 0
    for sequence, (_, _, path, _) in enumerate(samples):
        sample = json.loads(path.read_text())
        incoming = sample["objects"]
        if not isinstance(incoming, dict):
            raise ValueError("Replay sample objects must be an object")
        incoming = identities.convert(incoming)
        # Placement only replaces instances. Preserve floorplan objects captured by iFP.
        scope = sample.get("scope")
        replaced = {"instance", "macro"} if scope == "instances" else {"macro"}
        current = (
            {k: v for k, v in objects.items() if v["kind"] not in replaced}
            if scope in {"instances", "macros"}
            else {}
        )
        if scope == "access":
            current = {k: v for k, v in objects.items() if v["kind"] != "access_point"}
        if scope == "patch":
            current = objects.copy()
        if scope == "routing":
            current = {
                k: v
                for k, v in objects.items()
                if v["kind"] not in {"wire", "via", "guide", "route_patch", "access_point"}
                or (v["kind"] == "via" and v.get("net_kind", "signal") != "signal")
            }
        for key in sample.get("remove", []):
            current.pop(identities.reference(key), None)
        current.update(
            {k: v for k, v in incoming.items() if not (scope and k == "die" and k in current)}
        )
        if scope in {"instances", "macros"}:
            for key in incoming:
                if key in objects and key in current:
                    current[key] = {**objects[key], **current[key]}
                    if "pins" in objects[key] and "pins" not in incoming[key]:
                        dx = current[key]["bbox"][0] - objects[key]["bbox"][0]
                        dy = current[key]["bbox"][1] - objects[key]["bbox"][1]
                        current[key]["pins"] = {
                            name: {
                                **pin,
                                "position": [pin["position"][0] + dx, pin["position"][1] + dy],
                            }
                            for name, pin in objects[key]["pins"].items()
                        }
        for obj in current.values():
            bbox = obj["bbox"]
            if len(bbox) != 4 or any(type(v) is not int for v in bbox):
                raise ValueError("Replay bounds must be four integer DBU coordinates")
            if bbox[2] < bbox[0] or bbox[3] < bbox[1]:
                raise ValueError("Replay bounds are inverted")
        upsert = {k: v for k, v in current.items() if objects.get(k) != v}
        removed = [k for k in objects if k not in current]
        if sequence:
            changed_kinds = {v["kind"] for v in upsert.values()} | {
                objects[k]["kind"] for k in removed
            }
            for kind in changed_kinds:
                changes_by_kind[kind] = changes_by_kind.get(kind, 0) + 1
        identities.removed(removed)
        if sequence:
            # Metadata differences between tool domains do not imply movement.
            touched.update(
                k
                for k, v in upsert.items()
                if v["kind"] in {"instance", "macro"}
                and (
                    k not in objects
                    or v["bbox"] != objects[k]["bbox"]
                    or v.get("pins") != objects[k].get("pins")
                    or (
                        "master" in v
                        and "master" in objects[k]
                        and v["master"] != objects[k]["master"]
                    )
                    or (
                        "orient" in v
                        and "orient" in objects[k]
                        and v["orient"] != objects[k]["orient"]
                    )
                )
            )
            touched.update(k for k in removed if objects[k]["kind"] in {"instance", "macro"})
        if sequence == 0:
            baseline = current.copy()
        deleted.update({key: objects[key] for key in removed if key in touched})
        for key in current:
            deleted.pop(key, None)
        restored = [key for key in touched if key in current and current[key] == baseline.get(key)]
        subflow = sample["subflow"]
        if subflow not in subflows:
            subflows.append(subflow)
        folder = f"subflows/{subflows.index(subflow):03d}/frames"
        compact_upsert, translated = translations(objects, upsert)
        delta_bytes = len(json.dumps([compact_upsert, translated], separators=(",", ":"))) + sum(
            len(k) for k in removed
        )
        # Bound seek work by both changed bytes and depth. Sparse long histories
        # need fewer full copies; dense routing iterations get closer checkpoints.
        budget = min(64 * 1024 * 1024, max(256 * 1024, checkpoint_bytes // 2))
        checkpoint = (
            sequence == 0
            or sequence == len(samples) - 1
            or chain_frames >= 64
            or chain_bytes + delta_bytes > budget
        )
        if checkpoint:
            checkpoint_bytes = len(json.dumps(current, separators=(",", ":")))
            chain_bytes, chain_frames = 0, 0
        else:
            chain_bytes += delta_bytes
            chain_frames += 1
        relative = f"{folder}/{sequence:06d}.json"
        checkpoint_objects = current
        checkpoint_removed = []
        base_checkpoint = None
        if checkpoint and sequence:
            changed_from_input = {k: v for k, v in current.items() if baseline.get(k) != v}
            if len(changed_from_input) < len(current) // 2:
                checkpoint_objects = changed_from_input
                checkpoint_removed = [k for k in baseline if k not in current]
                base_checkpoint = 0
        relative, encoding = write_frame(
            directory,
            relative,
            {
                "sequence": sequence,
                "base_revision": sequence - 1,
                "checkpoint": checkpoint,
                "base_checkpoint": base_checkpoint,
                "upsert": checkpoint_objects if checkpoint else compact_upsert,
                "translate": {} if checkpoint else translated,
                "remove": checkpoint_removed if checkpoint else removed,
                "touched": sorted(touched),
                "deleted": deleted,
                "restored": sorted(restored),
            },
        )
        frames.append(
            {
                "sequence": sequence,
                "source_sequence": sample["sequence"],
                "producer": sample.get("producer", tool),
                "scope": sample.get("scope", "full"),
                "elapsed_ns": sample["elapsed_ns"],
                "phase": sample["phase"],
                "subflow": subflow,
                "state_domain": sample["state_domain"],
                "path": relative,
                "encoding": encoding,
                "checkpoint": checkpoint,
                "iteration": sample.get("iteration"),
                "logical": sample.get("logical"),
                "metrics": sample.get("metrics", {}),
            }
        )
        objects = current
    timing_path = directory / "capture/subflows.jsonl"
    timings = []
    previous_end = 0
    if timing_path.exists():
        events = [json.loads(line) for line in timing_path.read_text().splitlines()]
        stage_starts = {}
        for event in events:
            if event["state"] == "Ongoing":
                stage_starts.setdefault(event["name"], event["elapsed_ns"])
                continue
            end = event["elapsed_ns"]
            # run_fp returns once for four native stages; the Python ledger
            # acknowledges them together. Use each native stage's last sample.
            if step == "postFloorplan" and event["name"] in {
                "create tracks",
                "place io pins",
                "tap cell",
                "PDN",
            }:
                end = max(
                    (f["elapsed_ns"] for f in frames if f["subflow"] == event["name"]),
                    default=end,
                )
            start = stage_starts.pop(event["name"], previous_end)
            timings.append(
                {
                    "name": event["name"],
                    "state": event["state"],
                    "start_ns": start,
                    "end_ns": end,
                }
            )
            previous_end = end
    manifest = {
        "schema": "ecos.replay.v2",
        "attempt_id": attempt,
        "step": step,
        "tool": tool,
        "source": "captured",
        "history_completeness": "sampled",
        "capabilities": {
            "geometry": "report_only"
            if step in REPORT_ONLY
            else (
                "sampled_process"
                if any(count > 1 for count in changes_by_kind.values())
                else "final_diff"
            ),
            "changed_samples_by_kind": changes_by_kind,
            "observed_instance_lifetimes": True,
            "subsample_identity": "unobserved delete/recreate cannot be distinguished",
            "time_quality": "monotonic_anchored",
            "max_sample_gap_ns": max(
                (
                    b["elapsed_ns"] - a["elapsed_ns"]
                    for a, b in zip(frames, frames[1:], strict=False)
                ),
                default=0,
            ),
        },
        "status": "sealed" if defer_completion else "complete",
        "duration_ns": max(
            duration_ns,
            frames[-1]["elapsed_ns"],
            *(timing["end_ns"] for timing in timings),
        ),
        "frames": frames,
        "subflows": subflows,
        "subflow_timing": timings,
        "geometry_detail": "report_only" if step in REPORT_ONLY else "physical_bounds",
        "started_at_unix_ns": started_unix_ns,
        **(results or {}),
    }
    atomic_json(directory / "manifest.json", manifest)
    pointer = read_pointer(root)
    update_pointer(
        root,
        {
            "schema": manifest["schema"],
            "status": manifest["status"],
            "attempt_id": attempt,
            "manifest": f"attempts/{attempt}/manifest.json",
        },
        expected=attempt if pointer else None,
    )
    # Raw samples are staging data; published checkpoints/diffs own the history.
    shutil.rmtree(directory / "capture")
