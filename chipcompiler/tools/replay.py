"""Opt-in, offline Replay publication. Tool callbacks never own the flow ledger."""

import json
import logging
import os
import time
import uuid
from contextlib import contextmanager
from dataclasses import replace
from pathlib import Path

SUPPORTED = {"preFloorplan", "macroPlacement", "postFloorplan", "place"}
ENV_KEYS = (
    "ECC_REPLAY_CAPTURE_DIR",
    "ECC_REPLAY_START_NS",
    "ECC_REPLAY_STEP",
    "ECC_REPLAY_OFFSET_NS",
)
logger = logging.getLogger(__name__)


def capture_placement_result(workspace, step, ecc_module) -> None:
    """Finalize terminal Place Replay without invoking routing/map evaluation."""
    directory = os.environ.get("ECC_REPLAY_CAPTURE_DIR")
    if not directory:
        return
    committed = None
    try:
        from chipcompiler.data import StepInput, StepMetrics
        from chipcompiler.tools.ecc import runner
        from chipcompiler.tools.ecc.metrics import build_metrics_db, save_qor_metrics

        if ecc_module is not None:
            ecc_module.close()
        saved = replace(step, input=StepInput(def_=step.output.def_, verilog=step.output.verilog))
        committed = runner.create_db_engine(workspace, saved)
        if committed is None:
            raise ValueError("Cannot load committed placement for Replay")
        capture_native(committed, final=True)
        committed.feature_sammry(json_path=step.feature.db or "")
        metrics = StepMetrics()
        metrics.data = build_metrics_db(workspace, step)
        if not save_qor_metrics(workspace, step, metrics):
            raise OSError("Cannot save terminal placement Replay metrics")
    except Exception as error:
        logger.warning("Terminal placement Replay capture failed: %s", error)
        try:
            atomic_json(Path(directory) / "error.json", {"error": str(error)})
        except OSError:
            logger.warning("Cannot write Replay failure marker", exc_info=True)
    finally:
        if committed is not None:
            committed.close()


def capture_subflow(name: str, state: str) -> None:
    """Timestamp the real runner boundary, including stages without geometry changes."""
    directory = os.environ.get("ECC_REPLAY_CAPTURE_DIR")
    if not directory:
        return
    try:
        event = {
            "name": name,
            "state": state,
            "elapsed_ns": time.monotonic_ns() - int(os.environ["ECC_REPLAY_START_NS"]),
        }
        with (Path(directory) / "subflows.jsonl").open("a", encoding="utf-8") as stream:
            stream.write(json.dumps(event) + "\n")
    except OSError:
        logger.warning("Cannot capture Replay subflow timing", exc_info=True)


def capture_native(ecc_module, *, final: bool = False) -> None:
    """Capture the actual loaded/committed database, including no-op macro steps."""
    directory = os.environ.get("ECC_REPLAY_CAPTURE_DIR")
    if not directory:
        return
    path = Path(directory)
    try:
        objects = json.loads(ecc_module.ecc.replay_geometry())
        atomic_json(
            path / ("native-final.json" if final else "native-input.json"),
            {
                "sequence": 0,
                "elapsed_ns": time.monotonic_ns() - int(os.environ["ECC_REPLAY_START_NS"]),
                "phase": "committed_database" if final else "input_database",
                "subflow": "save data" if final else "load data",
                "state_domain": "native_committed" if final else "native_input",
                "objects": objects,
            },
        )
    except Exception as error:
        logger.warning("Replay database capture failed: %s", error)
        # A failed terminal sample must never publish an earlier algorithm frame.
        try:
            atomic_json(path / "error.json", {"error": str(error)})
        except OSError:
            logger.warning("Cannot write Replay failure marker", exc_info=True)


def anchor_native_capture() -> None:
    if os.environ.get("ECC_REPLAY_CAPTURE_DIR"):
        os.environ["ECC_REPLAY_OFFSET_NS"] = str(
            time.monotonic_ns() - int(os.environ["ECC_REPLAY_START_NS"])
        )


def atomic_json(path: Path, value: object) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(".tmp")
    temporary.write_text(json.dumps(value, ensure_ascii=False, allow_nan=False), encoding="utf-8")
    temporary.replace(path)


def read_settings(workspace) -> bool:
    """Read the canonical ECC CLI parameter; missing means disabled."""
    data = workspace.parameters.data.get("replay", {})
    if not isinstance(data, dict) or type(data.get("enabled", False)) is not bool:
        raise ValueError("replay.enabled must be a boolean")
    return data.get("enabled", False)


def publish(
    root: Path,
    attempt: str,
    step: str,
    tool: str,
    duration_ns: int,
    *,
    results: dict | None = None,
    started_unix_ns: int = 0,
) -> None:
    """Convert real tool samples to reversible semantic diffs and seek checkpoints."""
    directory = root / "attempts" / attempt
    if (directory / "capture" / "error.json").exists():
        raise ValueError("native Replay capture failed; see tool log")
    samples = []
    for path in (directory / "capture").glob("*.json"):
        sample = json.loads(path.read_text())
        samples.append((sample["elapsed_ns"], sample["sequence"], path, sample["state_domain"]))
    samples.sort(key=lambda entry: (entry[0], entry[1]))
    if not samples or samples[-1][3] != "native_committed":
        raise ValueError("tool did not provide a committed final Replay sample")
    objects, touched, frames, subflows = {}, set(), [], []
    for sequence, (_, _, path, _) in enumerate(samples):
        sample = json.loads(path.read_text())
        incoming = sample["objects"]
        if not isinstance(incoming, dict):
            raise ValueError("Replay sample objects must be an object")
        # Placement only replaces instances. Preserve floorplan objects captured by iFP.
        scope = sample.get("scope")
        replaced = {"instance", "macro"} if scope == "instances" else {"macro"}
        current = (
            {k: v for k, v in objects.items() if v["kind"] not in replaced}
            if scope in {"instances", "macros"}
            else {}
        )
        current.update(
            {k: v for k, v in incoming.items() if not (scope and k == "die" and k in current)}
        )
        if scope in {"instances", "macros"}:
            for key in incoming:
                if key in objects and key in current:
                    current[key] = {**objects[key], **current[key]}
        for obj in current.values():
            bbox = obj["bbox"]
            if len(bbox) != 4 or any(type(v) is not int for v in bbox):
                raise ValueError("Replay bounds must be four integer DBU coordinates")
            if bbox[2] < bbox[0] or bbox[3] < bbox[1]:
                raise ValueError("Replay bounds are inverted")
        upsert = {k: v for k, v in current.items() if objects.get(k) != v}
        removed = [k for k in objects if k not in current]
        if sequence:
            # Metadata differences between tool domains do not imply movement.
            touched.update(
                k
                for k, v in upsert.items()
                if v["kind"] in {"instance", "macro"}
                and (
                    k not in objects
                    or v["bbox"] != objects[k]["bbox"]
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
        subflow = sample["subflow"]
        if subflow not in subflows:
            subflows.append(subflow)
        folder = f"subflows/{subflows.index(subflow):03d}/frames"
        checkpoint = sequence % 16 == 0 or sequence == len(samples) - 1
        relative = f"{folder}/{sequence:06d}.json"
        atomic_json(
            directory / relative,
            {
                "sequence": sequence,
                "base_revision": sequence - 1,
                "checkpoint": checkpoint,
                "upsert": current if checkpoint else upsert,
                "remove": [] if checkpoint else removed,
                "touched": sorted(touched),
            },
        )
        frames.append(
            {
                "sequence": sequence,
                "elapsed_ns": sample["elapsed_ns"],
                "phase": sample["phase"],
                "subflow": subflow,
                "state_domain": sample["state_domain"],
                "path": relative,
                "checkpoint": checkpoint,
                "iteration": sample.get("iteration"),
                "metrics": sample.get("metrics", {}),
            }
        )
        objects = current
    timing_path = directory / "capture/subflows.jsonl"
    timings = []
    previous_end = 0
    if timing_path.exists():
        for line in timing_path.read_text().splitlines():
            event = json.loads(line)
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
            timings.append(
                {
                    "name": event["name"],
                    "state": event["state"],
                    "start_ns": previous_end,
                    "end_ns": end,
                }
            )
            previous_end = end
    manifest = {
        "schema": "ecos.replay.v1",
        "attempt_id": attempt,
        "step": step,
        "tool": tool,
        "source": "captured",
        "history_completeness": "sampled",
        "status": "complete",
        "duration_ns": max(duration_ns, frames[-1]["elapsed_ns"]),
        "frames": frames,
        "subflows": subflows,
        "subflow_timing": timings,
        "geometry_detail": "physical_bounds",
        "started_at_unix_ns": started_unix_ns,
        **(results or {}),
    }
    atomic_json(directory / "manifest.json", manifest)
    atomic_json(
        root / "manifest.json",
        {
            "schema": "ecos.replay.v1",
            "status": "complete",
            "attempt_id": attempt,
            "manifest": f"attempts/{attempt}/manifest.json",
        },
    )
    # Raw samples are staging data; published checkpoints/diffs own the history.
    for path in (directory / "capture").glob("*.json"):
        path.unlink()
    timing_path.unlink(missing_ok=True)
    (directory / "capture").rmdir()


@contextmanager
def capture_step(workspace, step):
    """Freeze opt-in per execution and clear inherited capture state for every tool."""
    previous = {key: os.environ.pop(key, None) for key in ENV_KEYS}
    geometry = getattr(step.output, "geometry", None)
    root = Path(geometry) / "replay" if geometry else None
    outcome = {"ok": False}
    started = time.monotonic_ns()
    started_unix_ns = time.time_ns()
    attempt = uuid.uuid4().hex
    enabled = False
    try:
        # Invalidate even a disabled or unsupported rerun, before invoking the tool.
        if root and (root / "manifest.json").exists():
            atomic_json(root / "manifest.json", {"schema": "ecos.replay.v1", "status": "stale"})
        enabled = step.name in SUPPORTED and root is not None and read_settings(workspace)
        if enabled and root is not None:
            capture = root / "attempts" / attempt / "capture"
            capture.mkdir(parents=True)
            atomic_json(
                root / "manifest.json",
                {"schema": "ecos.replay.v1", "status": "recording", "attempt_id": attempt},
            )
            os.environ.update(
                ECC_REPLAY_CAPTURE_DIR=str(capture),
                ECC_REPLAY_START_NS=str(started),
                ECC_REPLAY_STEP=step.name,
            )
        yield outcome
    finally:
        for key in ENV_KEYS:
            os.environ.pop(key, None)
            previous_value = previous[key]
            if previous_value is not None:
                os.environ[key] = previous_value
        if enabled and root is not None:
            try:
                if not outcome["ok"]:
                    raise ValueError("EDA step failed or was interrupted")
                from chipcompiler.tools.replay_results import collect_results

                results = collect_results(step, root / "attempts" / attempt, started_unix_ns)
                publish(
                    root,
                    attempt,
                    step.name,
                    step.tool,
                    time.monotonic_ns() - started,
                    results=results,
                    started_unix_ns=started_unix_ns,
                )
            except Exception as error:
                logger.warning("Replay unavailable for %s: %s", step.name, error)
                try:
                    atomic_json(
                        root / "manifest.json",
                        {
                            "schema": "ecos.replay.v1",
                            "status": "unavailable",
                            "attempt_id": attempt,
                            "reason": str(error),
                        },
                    )
                except OSError:
                    logger.warning(
                        "Cannot publish Replay failure; recording remains incomplete", exc_info=True
                    )
