# Runtime Sidecar RPC Guide

Workspace operations are exposed through the private ECC runtime sidecar:

```bash
ecc rpc serve --stdio
```

The sidecar speaks JSON-RPC 2.0 over stdio. Each JSON-RPC payload is framed with
a `Content-Length` header. Stdout is reserved for framed protocol messages;
diagnostics and tool output belong on stderr.

The legacy workspace command group and its custom server-shaped JSON envelope
are no longer supported. Project commands such as `ecc init`, `ecc run`,
`ecc status`, `ecc config`, and `ecc param` remain ordinary stateless CLI
commands.

## Framing

Each request is UTF-8 JSON preceded by a byte length:

```text
Content-Length: 72

{"jsonrpc":"2.0","method":"rpc.ping","params":{},"id":"ping-1"}
```

The server returns another framed payload:

```text
Content-Length: 54

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
      "Design": "gcd",
      "Top module": "gcd",
      "Clock": "clk",
      "Frequency max [MHz]": 100
    },
    "originVerilog": "/path/to/gcd.v",
    "rtlList": ["/path/to/gcd.v"]
  },
  "id": "create-1"
}
```

If `filelist` is omitted and `rtlList` is present, ECC writes a workspace-local
filelist before creating the workspace.

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

## Mutating Workspace Calls

The runtime serializes mutating calls for the same workspace session. Supported
first-slice mutation methods are:

- `workspace.refresh_config`
- `workspace.sync_config`
- `workspace.reset_flow`
- `flow.run`
- `flow.run_step`
- `workspace.close`

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
use ECC-specific messages in the JSON-RPC error `message` field, with details in
`data` when available.

Common runtime messages:

- `unsupported_version`: `rpc.hello` used an incompatible protocol version.
- `workspace_session_not_found`: the supplied `workspaceId` is unknown or
  closed.
- `invalid_request`: params are missing required fields or include unknown
  fields.
- `command_failed`: workspace or flow execution failed.
