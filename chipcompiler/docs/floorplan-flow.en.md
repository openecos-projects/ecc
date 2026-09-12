# Staged Floorplan Flow

The `rtl2gds` preset persists floorplanning as three separate stages:

```mermaid
flowchart LR
    LEC[LEC] --> PRE[preFloorplan\necc]
    PRE --> MACRO[macroPlacement\nDreamPlace]
    MACRO --> POST[postFloorplan\necc]
    POST --> PLACE[placement\nDreamPlace]
```

A normal `ecc run` executes the stages consecutively. They are separate so
each result, log, and flow state can be inspected or re-run independently.
The split does **not** add an automatic GUI pause protocol.

## Stages

| Persisted step | Tool | Workspace directory | What it does |
| --- | --- | --- | --- |
| `preFloorplan` | ecc | `preFloorplan_ecc/` | Builds the initial die/core plan with automatic macro placement enabled. It derives `config/floorplan_ecc_simple.json` from the shared floorplan configuration. |
| `macroPlacement` | DreamPlace | `macroPlacement_dreamplace/` | Runs macro-only placement from the pre-floorplan database, then writes the Tcl macro-location handoff. |
| `postFloorplan` | ecc | `postFloorplan_ecc/` | Loads the macro-location handoff in file mode and completes floorplanning: tracks, IO pins, tap/endcap cells, PDN, clock-net setup, outputs, and analysis. |

`Floorplan` remains the shared configuration key; it is not an executable flow
step. Use the three persisted names above when selecting steps in an existing
workspace.

## Macro-location handoff

After successful macro-only placement, the flow writes
`config/macro_localtion.tcl`. The filename intentionally retains the existing
`localtion` spelling for compatibility.

The file is the iDB/Tcl handoff between macro placement and post-floorplan.
Each hard macro is represented by these commands, with coordinates in microns:

```tcl
placeInstance <instance> <x_micron> <y_micron> <orientation>
setInstancePlacementStatus -status fixed -name <instance>
```

`postFloorplan` passes this file to iFP through `floorplan_ecc.json` with
`macro_placer.mode = "file"`. An empty file is valid for a design with no hard
macros. Every listed instance must exist in the design; old four-column
location text files are not valid handoffs. The generated orientation values
are `R0`, `R90`, `R180`, `R270`, `MY`, `MX90`, `MX`, and `MY90`.

If a GUI or a user supplies macro locations, it must write this same Tcl
format. Re-running `macroPlacement` regenerates the handoff, so run only
`postFloorplan` after replacing it with a valid manual handoff.

## Resuming or re-running stages

The normal command resumes from the first non-successful persisted step:

```bash
ecc run --workspace default --resume
```

For an existing workspace, `--from` and `--to` use the persisted camel-case
names. For example:

```bash
# Recreate the initial plan and macro handoff.
ecc run --workspace default --from preFloorplan --to macroPlacement

# Apply an existing or manually supplied Tcl handoff without rerunning macros.
ecc run --workspace default --from postFloorplan --to postFloorplan
```

Re-running a stage replaces that stage's output and marks downstream stages
for re-execution. On a new range workspace, `--from` and `--to` must be used
together and the entry step's required design inputs must already be declared.
See the [CLI User Guide](ecc-user-guide.en.md) for the full selector rules.

## Configuration

All floorplan stages share the workspace's `config/floorplan_ecc.json`.
`preFloorplan` uses a generated simple copy with `macro_placer.mode = "auto"`;
`postFloorplan` uses the shared file with the macro handoff in `file` mode.
Use `ecc param` or `ecc.toml` parameters to change reviewed floorplan settings
rather than relying on generated per-run values. The
[Configuration Reference](ecc-config-ref.en.md) lists the supported floorplan
parameters and JSON fields.
