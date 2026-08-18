# Step Marker Protocol

This document is the normative specification of the step marker protocol: the
byte-stream convention an executor process (CLI worker or GUI sidecar) uses to
delimit per-step tool output on its stderr stream, and the rules clients
follow to archive that output into per-step log files.

Status: v1, normative.

## Design Invariant

An executor process never opens, writes, or tails step log files. It writes
bytes to fd 1/2 and emits step markers on fd 2. Workspace state files
(flow.json, home.json) and the workspace logger (`log/<design>.log`) are
exempt from this rule; it applies to step tool logs only.

Each client (CLI, GUI) archives the byte stream into per-step log files as a
client-side result. Files are archival results: any tool that later reads a
step log (GUI history view, `ecc log`, failure-context extraction) is a
read-only consumer and does not care which client wrote it.

Markers are private to the byte-stream layer. A marker is only ever meaningful
between the producing executor and the consuming archiver in its client.
Matched markers are consumed by the archiver and are never archived, forwarded
to any user-visible surface, or shown to users.

## Frame Format

A marker frame is exactly one line on fd 2:

```
\x1e ECC-STEP <space> <compact JSON> \n
```

- `\x1e` is the ASCII Record Separator control character.
- The literal prefix `ECC-STEP ` (with one trailing space) follows.
- The payload is a single JSON object serialized without insignificant
  whitespace.
- The frame is terminated by a single `\n`.

Payload (version 1):

```json
{"v":1,"event":"begin","step":"Synthesis","tool":"yosys"}
{"v":1,"event":"end","step":"Synthesis","tool":"yosys"}
```

Fields:

- `v` (number, required): protocol version. This document defines version `1`.
- `event` (string, required): `begin` or `end`.
- `step` (string, required): the flow step name (e.g. `Synthesis`).
- `tool` (string, required): the tool identifier (e.g. `yosys`, `ecc`).

## Semantics

Producer rules (executor):

- `begin` is emitted when a step starts executing, before any of the step's
  tool output.
- `end` is emitted according to the ordering guarantee below.
- Emission is unconditional: every execution path has a consumer, so no mode
  flag exists.

Consumer rules (client archiver):

- A `begin` frame while no step is active: open/activate archival for
  `(step, tool)`. An `end` frame matching the active `(step, tool)`: close
  archival. Both frames are consumed (not archived).
- Any of the following is treated as ordinary stream bytes, never as a
  marker: a `begin` while a step is active, an `end` that does not match the
  active `(step, tool)`, an unknown `event`, a missing or unsupported `v`, or
  a malformed frame (bad JSON, non-dict payload, missing/wrong-typed fields).
- Bytes received while no step is active are *unscoped*: they are not
  attributed to any step and must not be written to any step log archive.
- Consumers must drain the stream continuously with a bounded buffer, and must
  bound every wait they place on marker arrival (an executor crash may mean an
  `end` frame never arrives).

## Ordering Guarantee

Within a step, the executor writes the `end` marker:

- **after** all step-scoped writes have flushed — final state persistence,
  `[RESULT]` logging, QOR/metrics refresh, layout snapshot, and db cleanup —
  so that a consumer that has read the `end` marker has seen every byte of
  that step; and
- **before** the step completion notification (`step.completed`) is published.

Because the previous step's final state is persisted before its `end` marker,
and the `end` marker precedes the next step's `begin` marker, a consumer may
refresh per-step final states from flow.json on each `begin` marker and once
more when the operation ends.

If a step's execution or post-processing raises, no `end` marker is emitted
for that step; consumers treat the missing `end` as a crash signal and must
not wait indefinitely for it.

## Single-Producer Invariant

At most one flow executes per executor process at a time:

- GUI: one sidecar per workspace, with `RuntimeOperationConflict` enforced per
  workspace.
- CLI: one worker per run operation.

Frames from different steps therefore never interleave on the stream; a
`begin` while a step is active indicates a protocol violation or foreign
output and is handled as ordinary bytes (see Semantics).

## Archive Path Layout

Clients archive step output to:

```
<workspace>/<Step>_<tool>/log/<Step>.log
```

Consumers must sanitize `step`/`tool` (reject path separators, `..`, and
empty names) and must verify the resolved path stays inside the workspace
directory before opening it. A frame that fails sanitization or containment
is degraded to ordinary bytes; its bytes are never written outside the
workspace.

The archive is opened with truncation on each accepted `begin`, so a rerun
starts a fresh byte stream with cursor 0.

## Allowlist

On top of sanitization and containment, consumers should restrict archival
to `(step, tool)` pairs read from the workspace's flow.json: a begin marker
whose pair is not in the allowlist degrades to ordinary bytes. The allowlist
is loaded at workspace open and refreshed when an operation starts and when
a rerun is prepared.

When flow.json cannot be read, each consumer picks its failure default and
documents it here:

- the **GUI** archiver fails closed (empty allowlist): all markers degrade
  to unscoped bytes, which still land in the sidecar log file, so no output
  is lost;
- the **CLI** reader fails open (no allowlist): markers are honored after
  sanitization and containment only, because the archived step logs are the
  CLI's only record of the run.

Both defaults are safe: containment bounds where bytes can be written, and
the bytes always land in a visible place.


## Protocol Change: Live-Log Events Are Client-Synthesized

As of this protocol version, ecc no longer emits `step.log` notifications or
attaches `finalLog` to `step.completed` on the runtime event channel. Live
step-log events are synthesized by the client that archives the stream:

- the CLI archives silently (its terminal UI renders from the same stream);
- the GUI's Electron process synthesizes `step.log` / `finalLog` events for
  its renderer from the archived bytes.

Consequence (DEC-1, accepted 2026-08-18): the GUI is the only supported
consumer of operation live logs. The event shapes the GUI renderer consumes
(`step.log` payload `{chunk, cursor, step, tool}`; `finalLog` on
`step.completed`) are unchanged — only their producer moved, from ecc
file-tailing to client-side synthesis. Versions are pinned via the
superproject's ecc submodule, so producer and consumer always match.
