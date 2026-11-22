# Offline Replay capture

Replay is an optional, offline output of the existing flow. It does not select,
reorder, skip, or insert steps. All standard steps are registered; their available history differs by producer. See the capability table below. Registration does not imply complete internal algorithm history.

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

Update ECC, ECC-Tools, ECC-DreamPlace, ECC-Sizer/OpenROAD, Kepler Formal and the Native reader together for new captures. Native accepts existing v1 and new v2 recordings. Capture disabled avoids database serialization and placement
coordinate copies. An old native tool with capture enabled produces an explicit
unavailable Replay rather than a fabricated recording.

## Capture ownership and hooks

| Step | Producer | Captured events |
| --- | --- | --- |
| preFloorplan | ECC-Tools iFP | loaded IDB; initialized working geometry; die/core, rows/tracks and IO placement; committed IDB |
| macroPlacement | ECC-DreamPlace | loaded IDB; macro algorithm samples if invoked; native committed result, including the no-macro/no-op case |
| postFloorplan | ECC-Tools iFP | loaded IDB; halo/row cutting, endcaps/taps, PDN generation boundaries; committed IDB |
| place | ECC-DreamPlace | loaded IDB; initial working state; every 30 pre-optimizer iterations; rollback; before/after legalization and detailed placement; placement end; writeback; committed IDB |

Additional producers and completion views (2026-11-16):

| Steps | Captured data / capability boundary |
| --- | --- |
| preplace / Timing optimization | ECC input/final geometry; OpenDB instance and pin changes at Sizer repair, legalization, ECO commit and rollback boundaries; CELL candidates annotate the process without replacing committed geometry |
| diff_opt / diff_buffering / diff_sizing / legalization | working coordinates, evaluated scalar decisions, native commits/refreshes and final database; candidates do not mutate physical history |
| CTS | physical instantiation/commit boundaries plus frozen completed hierarchical clock graph |
| route | PA iteration/completion access points, GR guides/phases, TA, DR iteration/best restoration/final metal; signal routing preserves PG geometry |
| filler | actual row batches and final database; completed post-route tree when produced |
| LVS / DRC / antenna | fresh source-bound violation locations/rules and final check results; no fabricated checking traversal |
| RCX / sta / powerAnalysis | SPEF net C and summed segment R, reported timing paths, per-instance power with exact-name resolution; not a complete RC graph |
| emir | actual solved voltage nodes and evaluated EM edges, including rule/coverage status |
| Synthesis | existing Yosys command-boundary logic JSON snapshots and grouped logical connectivity; no ABC internal search claim |
| lec / postRouteLec | Kepler structured stages/verdict/available counts plus authoritative result report; no fabricated partition or witness |
| Harden | LEF/LIB/GDS export begin/end, artifact size/hash, generated LEF boundary/pin/OBS and Liberty port/arc metadata |

`replay.sample_every_iterations` configures placement sampling (default 30).
Phase boundaries and final committed samples are retained regardless of interval.
Capabilities describe sampled history, observed identities and maximum sample gap.
Objects preserve native placed/fixed/master/orient, pin/net positions and real
routing segment/layer/width data where emitted. Scope-aware merging distinguishes
full snapshots, instances/macros, patch, routing and access points. Replay never
turns optimizer fillers or IO terminals into physical instance lifetimes.

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
    manifest.json                      # ecos.replay.v2, ordered frames/results
    subflows/000/frames/000000.json     # checkpoint or diff
    subflows/001/frames/000001.json.gz  # explicit gzip+json encoding
    subflows/analysis/overlays/index.json
    subflows/analysis/overlays/sources/ # frozen reports; checksums in manifest
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
`remove`, and cumulative `touched` instance IDs. V2 additionally supports `translate` (pure instance translation including pins), cumulative `deleted`/`restored` records, and explicit frame encoding (`json` or `gzip+json`). Each batch is validated before changing the scene. A checkpoint includes the full current scene. The first/final frames are checkpoints; intervening checkpoints bound cumulative changed bytes and chain depth (64 frames), rather than occurring every 16 frames.
Backward seek restores a preceding checkpoint then reapplies forward diffs;
diffs are not applied backward. Instance IDs start as `inst:<native name>`; observed deletion/recreation adds a birth suffix. Large shape keys are SHA-256 identifiers. Matching covers observed lifetimes only, not hidden operations between samples.
Objects have kind and four integer DBU bounds; native instances also retain
name/master/orientation/fixed metadata. Cell pin polygons and cell obstructions
are not part of this first physical-bounds recording.

The initial loaded scene has an empty touched set. Subsequent new, removed,
moved, resized or reoriented instances accumulate in `touched`, including cells
that later return to their initial position. Algorithm-only instance updates
preserve floorplan/PDN objects and native instance metadata. Deleted instances retain their last recorded geometry for deletion markers; returning to the initial state does not remove the touched history.

## Time, publication and rerun semantics

- Wall-clock `started_at_unix_ns` identifies the attempt; `capture_started_fs_ns` anchors report freshness to the same filesystem clock to tolerate NFS/client clock skew. It does not order animation frames.
- `elapsed_ns` and duration use monotonic time relative to step execution.
  ECC passes a common Python origin to DreamPlace and an offset to C++ steady
  clock snapshots. Capture timestamps are facts. The viewer may interpolate compatible samples as a labeled presentation effect; it does not invent additional algorithm samples.
- Capture environment variables are scoped to the active step and restored on
  exit. Normal execution isolates steps in subprocesses. Concurrent in-process
  execution sharing the global native database/environment is not supported.
- Before every rerun, an existing pointer is marked stale, even if capture is
  now disabled. Enabled runs first publish `recording` with a new attempt ID.
- Tool completion seals a candidate. Parent flow completion finalizes QoR/checklist before publishing `complete`; compare-and-replace attempt IDs reject late workers. A read-only failed check with fresh validated reports can publish `diagnostic_only` while its flow state remains `Incomplete`. Other failures and missing final data remain unavailable; an earlier attempt is never silently substituted.
- Publication uses file replacement, publishing the pointer last. Staging raw
  samples are deleted after success. Older attempt directories are retained but
  not selected; completed history is bounded to the current and one previous attempt; unfinished attempts and symlink targets are preserved.

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

## Filler helper analysis ownership (2026-11-18)

Filler inserts cells, saves DEF/DB/GDS/native geometry and records result metrics.
With geometry.clock_tree enabled it also invokes RCX, selects the TYPICAL/25°C
SPEF, and runs iSTA with TYP/25°C Liberty to obtain real clock-tree delays. This
is a clock visualization helper, not execution of the flow's independent RCX or
STA stage. The current RCX helper emits multiple corners before that selection.

Previously those helper runs leaked run-rcx events into the Filler capture, and
geometry_display.publish recursively bound their RCX datasets to Filler. The
Replay index then counted all datasets without checking their owning stage.
AES ws_0007 consequently presented nine SPEF extraction views under Filler.
This was incorrect result ownership, not evidence of incorrect parasitic values.

The helper now suspends ECC_REPLAY_CAPTURE_DIR while RCX/STA run and restores it
even on failure. Its computation, clock-tree provenance and capture opt-in remain
unchanged. RCX display assets may be bound/published as analysis only by the RCX
step. Native Replay applies the same ownership rule to existing captures and
their planned durations, and skips old auxiliary run-rcx animation clips after
applying their deltas. Immutable old captures are never edited in place.

Regression coverage lives in test/tools/test_geometry_display.py,
test/tools/test_replay_events.py and test/tools/ecc/test_clock_tree.py. Both enabled
and disabled capture preserve the clock helper's RCX → iSTA operation sequence;
nested/error paths restore the opt-in flag. The same RCX asset must remain visible
and counted in RCX while being excluded from Filler publication and Replay.

## Historical validation

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

## Current verification and known limits

The 2026-11-16 implementation passed `ruff check chipcompiler test`,
`ruff format --check chipcompiler test`, and `pytest -q test` (4468 passed,
6 skipped, 1 deselected, 4 xfailed). Real isolated GCD full/terminal-Place and
AES full flows were exercised; AES captured five detailed-routing iterations.
Harden parsing is tested with compressed DEF, nonzero die origin and nested
Liberty groups. ECC's LEF writer emits absolute coordinates, so these overlays
do not add the die origin a second time.

Frozen maps/clock-tree side files/reports/checklist are inventoried by size and
SHA-256. Structural deltas bind to the actual physical input, never GUI adjacency.
Electrical metric comparisons require complete compatible context; missing
context suppresses the delta. Capture failures cannot change tool success.

See Studio's `ecos/docs/replay-presentation.md` for reader/UI behavior and the
current performance/evidence ledger. CELL accepted/reverted batches, available
formal witness/cone evidence and real SPEF node/resistor graphs are now captured.
These remain bounded observations, not a complete transaction journal. Private
ICS55 extraction is observed at its wrapper; generic RCX also exposes internal
stable extraction boundaries. Publication retains current/previous completed
attempts and preserves unfinished attempts. The macro/rotation, capture-overhead
and full GPU/UI performance acceptance matrix remains tracked separately.

### Additional process and result contracts (2026-11-16)

- LVS entity/routing/PDN, DRC shape/check/report, antenna check/report events use
  the parent monotonic anchor. Their `patch` payload is empty and cannot erase
  the input layout. A real GCD suffix rerun verifies input precedes all events.
- Power overlays retain total/internal/switching/leakage watts separately.
  RCX retains ground and coupling capacitors in fF and resistor branches in ohm;
  coupling entries are not blindly summed across repeated net sections.
- `+base` checkpoint encodings merge changes/removals with checkpoint 0. The
  producer may not reference a different checkpoint or combine this with a
  translation delta. Native validates the reference before scene publication.
- Sizer candidate rows contain instance, previous/proposed master and the actual
  accept/revert decision, in batches of at most 128. They never mutate geometry.
- Formal logical evidence is frozen before staging cleanup. Counterexample cycle
  numbers are solver cycles, not wall-clock timestamps or physical coordinates.

### Observational capture and derived workspaces

Yosys JSON export sorts the active design. Logical capture therefore uses the
Yosys design stack with `try/finally` restoration; directly calling `write_json`
between synthesis passes changes subsequent mapping order. The capture-disabled
path does not snapshot. Actual Yosys tests compare cell traversal order and mapped
netlists and exercise failed exports. A real GCD off/on/off comparison produces
identical complete JSON netlists (358 cells in each run). The runner refreshes
the child offset after anchoring, rather than passing an earlier environment copy.

Workspace derivation preserves the sealed `output/geometry/replay` subtree byte
for byte. Its relative asset paths remain valid and absolute provenance strings
continue to identify original inputs. The general workspace path rewrite must
not rewrite those records or invalidate their indexed SHA-256 hashes. Rerun
invalidation still follows the actual reset range.

Bounded workspace derivation also regenerates/persists timing configuration after
replacing `origin/`. Otherwise the old DB configuration resurrects a deleted
pre-CTS SDC as a custom file and tools run without clocks. Engine/CLI derive
regressions (20 tests) verify generated pre/post-CTS files survive reopening.
The installed GCD off/on pair produced byte-identical normalized DEF outputs
and identical available non-runtime QoR; measured wall time was 116.944/127.224s
(single pair, 8.79% increase; not a general overhead guarantee).
