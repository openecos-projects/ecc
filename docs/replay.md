# Floorplan and Place Replay capture

Replay is an optional, offline output of the existing flow. It does not select,
reorder, skip, or insert steps. The first implementation captures `preFloorplan`,
`macroPlacement`, `postFloorplan`, and `place`; intervening steps such as
`preplace` still execute normally.

The timeline follows the workspace's actual `home/flow.json`, including flows
that start after synthesis or end before harden. Selecting `--to place` in a
longer flow and defining a flow whose last step is `place` are distinct cases;
both must be validated. Replay must never extend a flow to obtain reports.

## Enable capture

```sh
ecc param set replay.enabled true --project /path/to/project --workspace ws_0001 --plain
```

The canonical setting is `[params.replay] enabled = true` in the workspace's
`home/params.toml`. The parameter is output-only and defaults to false. Changing
it does not invalidate implementation results or rerun the flow. Explicitly run
the desired existing steps afterward. Studio's workspace wizard supplies the
same canonical parameter through ECC CLI workspace creation/parameter application.
There is no separate `home/replay.json` setting.

All three source components must be updated together: ECC, ECC-Tools, and
ECC-DreamPlace. Capture disabled avoids database serialization and placement
coordinate copies. An old native tool with capture enabled produces an explicit
unavailable Replay rather than a fabricated recording.

## Capture ownership and hooks

| Step | Producer | Captured events |
| --- | --- | --- |
| preFloorplan | ECC-Tools iFP | loaded IDB; initialized working geometry; die/core, rows/tracks and IO placement; committed IDB |
| macroPlacement | ECC-DreamPlace | loaded IDB; macro algorithm samples if invoked; native committed result, including the no-macro/no-op case |
| postFloorplan | ECC-Tools iFP | loaded IDB; halo/row cutting, endcaps/taps, PDN generation boundaries; committed IDB |
| place | ECC-DreamPlace | loaded IDB; initial working state; every 30 pre-optimizer iterations; rollback; before/after legalization and detailed placement; placement end; writeback; committed IDB |

Source entry points:

- `chipcompiler/tools/eda.py`: wraps the existing tool invocation in
  `chipcompiler/tools/replay.py::capture_step`; tool success remains authoritative.
- `chipcompiler/tools/ecc/runner.py`: captures loaded and saved native databases;
  anchors the iFP monotonic clock before initialization.
- ECC-Tools `src/operation/iFP/source/data_manager/ReplayCapture.{hpp,cpp}`:
  optional snapshots from floorplan algorithms. Hooks are in `FPInterface`,
  `DieBuilder`, `IOPlacer`, `PhyPlacer`, and `PDNGenerator`.
- ECC-Tools `src/interface/python/py_idb/py_replay.{h,cpp}`:
  `replay_geometry()` exports authoritative IDB bounds using GeometryBuilder.
- ECC-DreamPlace `dreamplace/replay_capture.py`, `NonLinearPlace.py`, and
  `macroPlaceDB.py`: algorithm coordinate sampling, rollback and final writeback.
- `chipcompiler/tools/replay_results.py`: freezes this attempt's QoR metrics and
  Place map CSVs. The original image-generation switches are independent of Replay.

Placement sampling converts the actual optimizer vector to integer DBU using
`round(position / scale_factor + shift_factor)`. It separates optimizer filler
nodes from physical nodes and excludes synthetic placement obstacles and
zero-area terminals. Instance bounds use native master dimensions rather than
optimization padding/inflation. Final master, orientation, placement status and
coordinates come from the committed IDB, not a last optimizer iteration.

iFP physical-cell capture uses each newly generated instance's placement
coordinates and oriented master dimensions. Its cached bounding rectangle can
still be empty until writeback; relying on that rectangle silently omits taps
and endcaps from intermediate frames. For the GCD regression, corner/endcap,
boundary and well-tap phases contain 86, 108 and 169 cumulative physical cells;
their recorded bounds must equal the final committed instance bounds.

## Persisted contract

```text
<step>_<tool>/output/geometry/replay/
  manifest.json                         # current attempt pointer/status
  attempts/<attempt_id>/
    manifest.json                      # ecos.replay.v1, ordered frames/results
    subflows/000/frames/000000.json     # checkpoint or diff
    subflows/001/frames/000001.json
    subflows/run-placement/overlays/maps/<category>/*.csv
```

The attempt manifest records step, tool, source=`captured`,
history_completeness=`sampled`, geometry_detail=`physical_bounds`,
`started_at_unix_ns`, `duration_ns`, ordered frames, metrics and optional map path. The `subflow_timing` array records
real runner boundaries (`name`, `state`, `start_ns`, `end_ns`), including analysis
and other stages with no geometry changes. Studio places subflow nodes at these
completion times; phase samples do not create extra subflow steps. For the four
postFloorplan stages batched inside `run_fp`, native stage-end samples supply
the boundary rather than the later Python ledger acknowledgements.
Each frame indexes `sequence`, `elapsed_ns`, phase, subflow, state domain,
iteration, optional process metrics, checkpoint flag and a relative path.
Numeric subflow directories map to names in the manifest; they are not inferred
from filesystem ordering.

Each geometry record contains `sequence`, `base_revision`, `checkpoint`, `upsert`,
`remove`, and cumulative `touched` instance IDs. A checkpoint includes the full
current scene. Frame zero, every 16th frame and the final frame are checkpoints.
Backward seek restores a preceding checkpoint then reapplies forward diffs;
diffs are not applied backward. IDs for instances are `inst:<native name>`.
Objects have kind and four integer DBU bounds; native instances also retain
name/master/orientation/fixed metadata. Cell pin polygons and cell obstructions
are not part of this first physical-bounds recording.

The initial loaded scene has an empty touched set. Subsequent new, removed,
moved, resized or reoriented instances accumulate in `touched`, including cells
that later return to their initial position. Algorithm-only instance updates
preserve floorplan/PDN objects and native instance metadata. Deleted instances
remain counted in the touched set but have no geometry to outline.

## Time, publication and rerun semantics

- Wall-clock `started_at_unix_ns` identifies the attempt and filters out stale
  reports. It does not order animation frames.
- `elapsed_ns` and duration use monotonic time relative to step execution.
  ECC passes a common Python origin to DreamPlace and an offset to C++ steady
  clock snapshots. Sampling gaps hold the last recorded scene; no unrecorded
  algorithm trajectories are interpolated.
- Capture environment variables are scoped to the active step and restored on
  exit. Normal execution isolates steps in subprocesses. Concurrent in-process
  execution sharing the global native database/environment is not supported.
- Before every rerun, an existing pointer is marked stale, even if capture is
  now disabled. Enabled runs first publish `recording` with a new attempt ID.
- Only successful tool execution with a final native committed sample publishes
  `complete`. Failure, interruption or capture error leaves unavailable or
  incomplete data; an earlier attempt is not silently substituted.
- Publication uses file replacement, publishing the pointer last. Staging raw
  samples are deleted after success. Older attempt directories are retained but
  not selected; automatic disk retention is not yet implemented.

## Completion metrics and maps

`analysis/qor_metrics.json` is copied into the attempt manifest only when freshly
written during this execution. Runtime-category metrics are excluded because
the flow engine finalizes resource observations after the tool returns; a new
QoR file can still retain the previous attempt's resource fields. Replay displays
its monotonic capture duration separately. Place maps copy fresh `feature/*_map/*.csv`
together with their fresh `layout.csv`, under the subflow geometry directory.
`layout.csv` supplies spatial coordinates; pixel dimensions are not used to
guess layout positions. Reports/maps are displayed only at the completion node.
Missing or stale reports are not replaced with invented values.

When Place is the final step in the configured flow, its existing
`placement_only` branch intentionally skips ordinary save/analysis stages to
avoid starting routing evaluation. With Replay enabled, it reloads the saved
DEF/Verilog, captures full committed geometry, and extracts database summary
metrics only. It does not invoke routing or map evaluation. Only fresh maps
actually produced by this attempt are available at completion.

Worker subflow events carry completion metadata, not only UI notifications.
`step_subprocess._replay_events` must restore them into the parent's subflow
state even without an observer, and independently of the notification cursor.
Otherwise the parent loses `placement_only` and rejects a successful terminal
Place for lacking the ordinary geometry snapshot. Replay does not bypass the
flow completion check: terminal Place still requires saved DEF and Verilog.

## Validation

```sh
.venv/bin/python -m pytest test/tools/test_replay.py test/tools/test_eda_loader.py test/tools/ecc/test_runner.py test/tools/ecc_dreamplace test/cli/params test/data/test_parameter_keys.py -q
.venv/bin/ruff check chipcompiler/tools/replay.py chipcompiler/tools/replay_results.py test/tools/test_replay.py
.venv/bin/basedpyright chipcompiler/tools/replay.py chipcompiler/tools/replay_results.py
.venv/bin/python -m pytest test/engine/test_step_subprocess.py test/tools/test_replay_terminal.py -q
# From chipcompiler/thirdparty/ecc-dreamplace:
PYTHONPATH=. ../../../.venv/bin/python tests/ops/replay_capture_unittest.py
```

Real integration validation used an isolated copy of GCD, running the original
`preFloorplan → macroPlacement → postFloorplan → preplace → place` sequence.
It produced 6/2/18/21 frames respectively for the four captured steps, actual
placement movement, committed native geometry, final QoR metrics and spatial
map CSVs. GCD has no hard macros: active macro movement still needs a macro-rich
design validation. Other flow stages and full physical signoff are outside this
first capture implementation.

Terminal-flow regression also runs GCD with its original six-step flow ending
at Place. Validate worker metadata with and without an observer, a shortened
event list on rerun, capture disabled, committed-output reload, and unavailable
capture on database load failure. The real run must preserve upstream states
and flow boundaries while publishing committed final geometry and fresh metrics.
