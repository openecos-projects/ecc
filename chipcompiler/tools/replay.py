"""Opt-in, offline Replay publication. Tool callbacks never own the flow ledger."""

import json
import logging
import os
import time
from contextlib import contextmanager
from dataclasses import replace
from pathlib import Path

from chipcompiler.tools.replay_publish import publish
from chipcompiler.tools.replay_storage import atomic_json, read_pointer, replay_root, update_pointer

SUPPORTED = {
    "Synthesis",
    "lec",
    "preFloorplan",
    "macroPlacement",
    "postFloorplan",
    "preplace",
    "place",
    "diff_opt",
    "diff_buffering",
    "diff_sizing",
    "CTS",
    "legalization",
    "Timing optimization",
    "route",
    "filler",
    "lvs",
    "drc",
    "antennaCheck",
    "postRouteLec",
    "RCX",
    "sta",
    "powerAnalysis",
    "emir",
    "Harden",
}
ENV_KEYS = (
    "ECC_REPLAY_CAPTURE_DIR",
    "ECC_REPLAY_START_NS",
    "ECC_REPLAY_STEP",
    "ECC_REPLAY_OFFSET_NS",
    "ECC_REPLAY_SAMPLE_ITERATIONS",
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


def capture_step_database(workspace, step, *, final: bool = False) -> None:
    """Load a real input or committed DEF through ECC for tools outside ECC's runner."""
    directory = os.environ.get("ECC_REPLAY_CAPTURE_DIR")
    if not directory:
        return
    from chipcompiler.data import StepInput
    from chipcompiler.tools.ecc import runner

    source = (
        replace(step, input=StepInput(def_=step.output.def_, verilog=step.output.verilog))
        if final
        else step
    )
    try:
        module = runner.create_db_engine(workspace, source)
        if module is None:
            raise ValueError("Cannot load step database for Replay")
        capture_native(module, final=final)
    except Exception as error:
        logger.warning("Replay database capture failed: %s", error)
        try:
            atomic_json(Path(directory) / "error.json", {"error": str(error)})
        except OSError:
            logger.warning("Cannot write Replay failure marker", exc_info=True)
    finally:
        if "module" in locals() and module is not None:
            try:
                module.close()
            except Exception as error:
                logger.warning("Cannot close Replay database capture: %s", error)


def anchor_native_capture() -> None:
    if os.environ.get("ECC_REPLAY_CAPTURE_DIR"):
        os.environ["ECC_REPLAY_OFFSET_NS"] = str(
            time.monotonic_ns() - int(os.environ["ECC_REPLAY_START_NS"])
        )


def read_settings(workspace) -> bool:
    """Read the canonical ECC CLI parameter; missing means disabled."""
    data = workspace.parameters.data.get("replay", {})
    if not isinstance(data, dict) or type(data.get("enabled", False)) is not bool:
        raise ValueError("replay.enabled must be a boolean")
    return data.get("enabled", False)


@contextmanager
def capture_step(workspace, step, *, attempt_id: str | None = None):
    """Freeze opt-in per execution and clear inherited capture state for every tool."""
    previous = {key: os.environ.pop(key, None) for key in ENV_KEYS}
    root = replay_root(step)
    outcome = {"ok": False}
    started = time.monotonic_ns()
    started_unix_ns = time.time_ns()
    attempt = attempt_id
    enabled = False
    log_capture = None
    try:
        try:
            from chipcompiler.tools.replay_completion import prepare

            if attempt is None:
                attempt = prepare(workspace, step)
            enabled = attempt is not None and root is not None
            if enabled:
                if read_pointer(root).get("attempt_id") != attempt:
                    raise ValueError("Replay attempt was superseded before capture")
                capture = root / "attempts" / attempt / "capture"
                capture.mkdir(parents=True)
                from chipcompiler.tools.replay_metrics import capture_baseline

                atomic_json(capture.parent / "baseline.json", capture_baseline(step))
                # Reports and this marker share the filesystem clock. NFS mtime
                # can lag the client's wall clock even for a newly written file.
                capture_started_fs_ns = (capture.parent / "baseline.json").stat().st_mtime_ns
                interval = workspace.parameters.data.get("replay", {}).get(
                    "sample_every_iterations", 30
                )
                if type(interval) is not int or interval <= 0:
                    raise ValueError("replay.sample_every_iterations must be a positive integer")
                os.environ.update(
                    ECC_REPLAY_CAPTURE_DIR=str(capture),
                    ECC_REPLAY_START_NS=str(started),
                    ECC_REPLAY_STEP=step.name,
                    ECC_REPLAY_SAMPLE_ITERATIONS=str(interval),
                )
                from chipcompiler.tools.replay_log import LogCapture

                log_capture = LogCapture.start(workspace, step, capture.parent, started)
        except Exception as error:
            logger.warning("Replay setup failed for %s: %s", step.name, error)
            for key in ENV_KEYS:
                os.environ.pop(key, None)
            enabled = False
            if root is not None and attempt is not None:
                try:
                    update_pointer(
                        root,
                        {"status": "unavailable", "attempt_id": attempt, "reason": str(error)},
                        expected=attempt,
                    )
                except OSError:
                    logger.warning("Cannot record Replay setup failure", exc_info=True)
        yield outcome
    finally:
        log_result = {}
        if log_capture is not None:
            try:
                log_result = log_capture.finish()
            except (OSError, ValueError) as error:
                logger.warning("Replay log finalization failed: %s", error)
                log_result = {"log_unavailable": str(error)}
        for key in ENV_KEYS:
            os.environ.pop(key, None)
            previous_value = previous[key]
            if previous_value is not None:
                os.environ[key] = previous_value
        if enabled and root is not None:
            try:
                from chipcompiler.tools.replay_results import collect_results

                results = collect_results(
                    step,
                    root / "attempts" / attempt,
                    capture_started_fs_ns,
                    workspace.directory,
                )
                results.update(log_result)
                results["capture_started_fs_ns"] = capture_started_fs_ns
                if not outcome["ok"]:
                    from chipcompiler.tools.replay_diagnostics import require_evidence

                    require_evidence(step.name, root / "attempts" / attempt, results)
                publish(
                    root,
                    attempt,
                    step.name,
                    step.tool,
                    time.monotonic_ns() - started,
                    results=results,
                    started_unix_ns=started_unix_ns,
                    defer_completion=True,
                )
                if attempt_id is None:
                    from chipcompiler.tools.replay_completion import finalize

                    finalize(workspace, step, attempt, "Success" if outcome["ok"] else "Incomplete")
            except Exception as error:
                logger.warning("Replay unavailable for %s: %s", step.name, error)
                try:
                    update_pointer(
                        root,
                        {
                            "schema": "ecos.replay.v1",
                            "status": "unavailable",
                            "attempt_id": attempt,
                            "reason": str(error),
                        },
                        expected=attempt,
                    )
                except OSError:
                    logger.warning(
                        "Cannot publish Replay failure; recording remains incomplete", exc_info=True
                    )
