# Runtime Sidecar RPC Guide

Workspace operations are exposed through the private ECC runtime sidecar:

```bash
ecc rpc serve --stdio
```

Persistent ECC DB reuse is disabled by default. To expose the explicit DB
lifecycle methods, start the sidecar with:

```bash
ecc rpc serve --stdio --persistent-db
```

The sidecar speaks JSON-RPC 2.0 over stdio. Each JSON-RPC payload is framed with
a `Content-Length` header. Stdout is reserved for framed protocol messages;
diagnostics and tool output belong on stderr.

The public CLI supports two commands from this resource area: `ecc workspace
refresh NAME`, which reconstructs a workspace already declared in
`project.json` from the current `ecc.toml` without executing the flow, and
`ecc workspace import NAME --path /absolute/workspace`, which registers an
existing workspace directory in `project.json` without changing or running
it. The legacy workspace create/run commands and their custom server-shaped
JSON envelope are not supported. Project commands such as `ecc init`,
`ecc run`, `ecc status`, `ecc config`, and `ecc param` remain ordinary
stateless CLI commands.

## Framing

Each request is UTF-8 JSON preceded by a byte length:

```text
Content-Length: 63

{"jsonrpc":"2.0","method":"rpc.ping","params":{},"id":"ping-1"}
```

The server returns another framed payload:

```text
Content-Length: 52

{"jsonrpc":"2.0","result":{"ok":true},"id":"ping-1"}
```

## Handshake

Call `rpc.hello` first to verify protocol compatibility and discover the
first-slice method list:

```json
{
  "jsonrpc": "2.0",
  "method": "rpc.hello",
  "params": {
    "version": 1
  },
  "id": "hello-1"
}
```

The result includes `version`, `eccVersion`, and `capabilities`.

Default `ecc rpc serve --stdio` capabilities include Candidate methods
(`candidate.capabilities`, `candidate.rerun`, `candidate.resume`) composed
onto the generic runtime. They do not include persistent DB methods. When
`--persistent-db` is enabled, `rpc.hello` also advertises `db.ensure` and
`db.release`.

## Open A Workspace

Open an existing workspace directory:

```json
{
  "jsonrpc": "2.0",
  "method": "workspace.open",
  "params": {
    "directory": "/path/to/gcd"
  },
  "id": "open-1"
}
```

The result returns a session identifier:

```json
{
  "workspaceId": "workspace-1",
  "directory": "/path/to/gcd"
}
```

Follow-up workspace and flow calls use `workspaceId`. They do not take the
workspace directory again unless the method explicitly documents a directory
parameter.

Opening or creating a workspace does not initialize persistent native DB state.
Persistent DB reuse starts only after an explicit `db.ensure` call in a sidecar
process started with `--persistent-db`.

## Create A Workspace

Create accepts the workspace directory, PDK name, optional PDK paths, design
parameters, and optional input files:

```json
{
  "jsonrpc": "2.0",
  "method": "workspace.create",
  "params": {
    "directory": "/path/to/gcd",
    "pdk": "ics55",
    "pdkRoot": "/path/to/icsprout55-pdk",
    "parameters": {
      "design": "gcd",
      "top_module": "gcd",
      "clock": "clk",
      "frequency_max": 100
    },
    "originVerilog": "/path/to/gcd.v",
    "rtlList": ["/path/to/gcd.v"]
  },
  "id": "create-1"
}
```

If `filelist` is omitted and `rtlList` is present, ECC writes a workspace-local
filelist before creating the workspace.

## Derive A Workspace

`workspace.derive` copies an existing workspace into a new directory with a
fresh identity: a new Engineering Snapshot (`workspaceRevision` 1, cause
`workspace.derived`), an empty runtime command ledger, and no inherited
workspace command records. The source directory stays read-only and
byte-identical. `resetFromStep` is optional; empty resets the whole flow for a
rerun, while a step name resets only that step and its flow suffix.

```json
{
  "jsonrpc": "2.0",
  "method": "workspace.derive",
  "params": {
    "directory": "/path/to/gcd",
    "targetDirectory": "/path/to/gcd-rerun",
    "resetFromStep": "Floorplan",
    "commandId": "derive-1"
  },
  "id": "derive-1"
}
```

The result has the same shape as `workspace.open` (`workspaceId`,
`workspaceRevision`, `directory`) with the derived workspace id.

## Inspect A Workspace

Use the returned `workspaceId` to inspect session state:

```json
{
  "jsonrpc": "2.0",
  "method": "workspace.home",
  "params": {
    "workspaceId": "workspace-1"
  },
  "id": "home-1"
}
```

Tool-specific step information is available through `workspace.info`:

```json
{
  "jsonrpc": "2.0",
  "method": "workspace.info",
  "params": {
    "workspaceId": "workspace-1",
    "step": "Synthesis",
    "id": "layout"
  },
  "id": "info-1"
}
```

Common info ids include `views`, `layout`, `metrics`, `subflow`, `analysis`,
`maps`, `checklist`, `sta`, and `config`.

## Read And Update Workspace Configuration

`workspace.configuration.read` takes a workspace `directory` (no session
required) and returns the workspace-level configuration. Its mutating
counterpart `workspace.configuration.update` takes `workspaceId`,
`expectedWorkspaceRevision` (optimistic concurrency), a `commandId` for
idempotency, the new `configuration`, and `workspaceBindings`.

Per-step parameters go through `workspace.step_configuration.read` /
`workspace.step_configuration.update`. The read takes `step` plus exactly
one of `workspaceId` or `directory`; when the step has no derived
configuration it returns `status: "unavailable"` with a `reason` instead of
an error. The update takes `workspaceId`, `expectedWorkspaceRevision`,
`stepId`, and a `parameters` map:

```json
{
  "jsonrpc": "2.0",
  "method": "workspace.step_configuration.update",
  "params": {
    "workspaceId": "workspace-1",
    "expectedWorkspaceRevision": 3,
    "commandId": "param-save-42",
    "stepId": "place",
    "parameters": {
      "place.target_density": 0.6
    }
  },
  "id": "step-cfg-1"
}
```

A step-configuration update persists the parameters, refreshes the derived
`config/*.json`, marks the step and its downstream suffix stale, and bumps
the Engineering Snapshot `workspaceRevision`.

## Describe And Validate A Workspace Spec

`workspace_spec.describe` (no params) returns the declarative workspace-spec
contract: `schemaVersion`, `flowDefinitions` (flow id to ordered step ids),
`inputRoleRules`, and a `parameterCatalog`. Each catalog record carries the
canonical parameter `id`, `type`, `default`, `appliesTo`,
`backendMapping`, optional `range` / `choices` / `unit`, plus `display_key`
and `knob_id`. Those two fields come from `chipcompiler/data/param_keys.py`
and are the authoritative mapping from GUI display keys and Agent knob ids
to canonical parameter ids — the GUI and the Agent must not hardcode their
own key tables.

`workspace_spec.validate` checks a candidate `workspaceSpec` document
together with its `workspaceBindings` and returns an `issues` list (empty
when the spec is valid) instead of raising:

```json
{
  "jsonrpc": "2.0",
  "method": "workspace_spec.validate",
  "params": {
    "workspaceSpec": {
      "schemaVersion": 1,
      "design": "gcd"
    },
    "workspaceBindings": {}
  },
  "id": "spec-validate-1"
}
```

Both methods are part of the v1 workspace contract; an older embedder that
lacks them receives a stable invalid-request result instead of a server
startup failure.

## Mutating Workspace Calls

The runtime serializes mutating calls for the same workspace session. Supported
first-slice mutation methods are:

- `workspace.refresh_config`
- `workspace.sync_config`
- `workspace.reset_flow`
- `workspace.derive`
- `workspace.configuration.update`
- `workspace.step_configuration.update`
- `workspace.export_signoff`
- `workspace.inspect_signoff`
- `flow.run`
- `flow.run_step`
- `workspace.close`

`workspace.export_signoff` takes `workspaceId`, `outputPath`, and optional
`additionalFiles`, and writes the signoff package archive, returning the
resolved `outputPath`. `workspace.inspect_signoff` returns the signoff
package readiness summary for the workspace.

`workspace.sync_config` requires `configPath` to be inside the workspace
`config/` directory:

```json
{
  "jsonrpc": "2.0",
  "method": "workspace.sync_config",
  "params": {
    "workspaceId": "workspace-1",
    "configPath": "/path/to/gcd/config/route.json"
  },
  "id": "sync-1"
}
```

`flow.run` with `rerun: true` re-executes the persisted flow from scratch
and preserves the workspace's current parameter values (GUI parity). Pass
`resetRuntimeParams: true` to make the runtime-parameter reset explicit:
the template die/core parameters are restored and the generated configs
refreshed before the rerun.

Run a single step:

```json
{
  "jsonrpc": "2.0",
  "method": "flow.run_step",
  "params": {
    "workspaceId": "workspace-1",
    "step": "Synthesis",
    "rerun": false
  },
  "id": "step-1"
}
```

## Persistent DB Lifecycle

Persistent DB lifecycle calls are private runtime capabilities and are available
only when the sidecar was started with `--persistent-db`.

Ensure a session-scoped DB handle:

```json
{
  "jsonrpc": "2.0",
  "method": "db.ensure",
  "params": {
    "workspaceId": "workspace-1",
    "step": "Floorplan"
  },
  "id": "db-ensure-1"
}
```

The `step` field is optional. When omitted, ECC uses the existing flow rule for
selecting the first unfinished step. A successful result reports whether the
handle is active and whether an existing handle was reused:

```json
{
  "workspaceId": "workspace-1",
  "enabled": true,
  "active": true,
  "reused": false,
  "step": "Floorplan"
}
```

Release the active session DB handle:

```json
{
  "jsonrpc": "2.0",
  "method": "db.release",
  "params": {
    "workspaceId": "workspace-1"
  },
  "id": "db-release-1"
}
```

`db.release` is idempotent and returns `released: false` when the session has no
active DB handle. Workspace refresh, changed config sync, reset, rerun, close,
replacement, and shutdown release stale handles. `flow.run` and `flow.run_step`
reuse and capture DB state only when the session already has an active handle
from `db.ensure`; otherwise their DB use remains transient.

## Shutdown

End the sidecar with `rpc.shutdown`:

```json
{
  "jsonrpc": "2.0",
  "method": "rpc.shutdown",
  "id": "shutdown-1"
}
```

The server closes workspace sessions and exits after the response is written.

## Errors

JSON-RPC validation errors use standard JSON-RPC error objects. Runtime errors
use ECC-specific code strings in the JSON-RPC error `message` field, with
human-readable details in `data.message` when available.

Common runtime error messages:

- `unsupported_version`: `rpc.hello` used an incompatible protocol version.
- `workspace_session_not_found`: the supplied `workspaceId` is unknown or
  closed.
- `invalid_request`: params are missing required fields or include unknown
  fields.
- `command_failed`: workspace or flow execution failed.
