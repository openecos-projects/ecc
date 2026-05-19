# Workspace CLI Guide

`ecc workspace` exposes the legacy runtime workspace API as CLI commands. Use it
when you need to create or operate on an old-style ECC workspace directory whose
state lives directly under the workspace root:

```text
gcd/
├── home/
│   ├── parameters.json
│   ├── flow.json
│   └── home.json
├── origin/
└── <step workspace directories>
```

This command group is separate from the newer project workflow used by
`ecc init`, `ecc check`, `ecc run`, `ecc status`, and `runs/default`.
Workspace commands do not auto-detect an `ecc.toml` project and do not remember
a current workspace between commands.

## Command Summary

```bash
ecc workspace create --directory gcd --pdk ics55 --pdk-root /path/to/icsprout55-pdk --param-json params.json
ecc workspace load --directory gcd
ecc workspace run-flow --directory gcd
ecc workspace run-flow --directory gcd --rerun
ecc workspace run-step --directory gcd --step Synthesis
ecc workspace get-info --directory gcd --step Synthesis --id layout
ecc workspace get-home --directory gcd
```

Add `--json` to any command to get a server-shaped response object:

```json
{
  "cmd": "load_workspace",
  "response": "success",
  "data": {},
  "message": []
}
```

`success` and `warning` return exit code 0. `failed` and `error` return exit
code 1.

## Create A Workspace

The minimum practical `create` command needs a workspace directory, a PDK name,
a PDK root, and design parameters:

```bash
cat > params.json <<'JSON'
{
  "Design": "gcd",
  "Top module": "gcd",
  "Clock": "clk",
  "Frequency max [MHz]": 100
}
JSON

ecc workspace create \
  --directory gcd \
  --pdk ics55 \
  --pdk-root /home/Emin/Workbench/icsprout55-pdk \
  --param-json params.json
```

Important parameter meanings:

- `--directory` is the workspace directory to create, for example `gcd`.
- `--pdk` is the PDK name, for example `ics55`.
- `--pdk-root` is the filesystem path to the PDK installation.
- `--param-json` points to a JSON object with ECC parameters.

`--pdk /path/to/pdk` is wrong: it passes the path as the PDK name. Use
`--pdk ics55 --pdk-root /path/to/pdk`.

`Top module` is required for flow workspace initialization. There is no separate
`--top` or `--topname` flag in this command group; pass it through
`--param-json` or `--input-json`.

## Add RTL Inputs

For a single Verilog source, pass both `--origin-verilog` and `--rtl`:

```bash
ecc workspace create \
  --directory gcd \
  --pdk ics55 \
  --pdk-root /home/Emin/Workbench/icsprout55-pdk \
  --origin-verilog /path/to/gcd.v \
  --rtl /path/to/gcd.v \
  --param-json params.json
```

For multiple RTL sources, repeat `--rtl`:

```bash
ecc workspace create \
  --directory gcd \
  --pdk ics55 \
  --pdk-root /home/Emin/Workbench/icsprout55-pdk \
  --origin-verilog /path/to/top.v \
  --rtl /path/to/top.v \
  --rtl /path/to/block.v \
  --rtl /path/to/package.sv \
  --param-json params.json
```

If `--filelist` is not provided and `--rtl` is present, the CLI writes a
workspace-local filelist and passes that to workspace creation.

If you already have a filelist, use `--filelist`:

```bash
ecc workspace create \
  --directory gcd \
  --pdk ics55 \
  --pdk-root /home/Emin/Workbench/icsprout55-pdk \
  --origin-verilog /path/to/top.v \
  --filelist /path/to/files.f \
  --param-json params.json
```

## JSON Input

For scripts and adapters, `create` can read the complete request object from a
JSON file:

```json
{
  "directory": "gcd",
  "pdk": "ics55",
  "pdk_root": "/home/Emin/Workbench/icsprout55-pdk",
  "parameters": {
    "Design": "gcd",
    "Top module": "gcd",
    "Clock": "clk",
    "Frequency max [MHz]": 100
  },
  "origin_def": "",
  "origin_verilog": "/path/to/gcd.v",
  "filelist": "",
  "rtl_list": ["/path/to/gcd.v"]
}
```

Run it with:

```bash
ecc workspace create --input-json request.json --json
```

You can also read from stdin:

```bash
cat request.json | ecc workspace create --input-json - --json
```

`--input-json` is mutually exclusive with the field flags such as `--directory`,
`--pdk`, `--rtl`, and `--param-json`.

Relative `origin_def`, `origin_verilog`, `filelist`, and `rtl_list` paths inside
a JSON file are resolved relative to that JSON file. When reading JSON from
stdin, relative paths are resolved relative to the current working directory.

## Load And Run

Load reconstructs the runtime workspace and initializes step workspaces if
needed:

```bash
ecc workspace load --directory gcd
```

Run the full flow:

```bash
ecc workspace run-flow --directory gcd
```

Rerun the full flow from a clean state:

```bash
ecc workspace run-flow --directory gcd --rerun
```

Run a single step:

```bash
ecc workspace run-step --directory gcd --step Synthesis
```

Rerun a single step:

```bash
ecc workspace run-step --directory gcd --step Synthesis --rerun
```

Step names are the flow step names stored in `home/flow.json`, such as
`Synthesis`, `Floorplan`, `place`, `CTS`, or `route`, depending on the generated
flow.

## Inspect Workspace Data

Get the `home/home.json` path:

```bash
ecc workspace get-home --directory gcd
```

Get tool-specific step information:

```bash
ecc workspace get-info --directory gcd --step Synthesis --id layout
ecc workspace get-info --directory gcd --step Synthesis --id metrics
ecc workspace get-info --directory gcd --step Synthesis --id subflow
ecc workspace get-info --directory gcd --step Synthesis --id config
```

Common `--id` values include:

- `views`
- `layout`
- `metrics`
- `subflow`
- `analysis`
- `maps`
- `checklist`
- `sta`
- `config`

If a step has no data for an id, the command returns `warning` and exit code 0.

## Common Errors

### `missing required field: directory`

`workspace create` does not accept a positional directory. Use:

```bash
ecc workspace create --directory gcd ...
```

not:

```bash
ecc workspace create gcd
```

### `PDK tech LEF is missing`

Check that `--pdk` and `--pdk-root` are not swapped:

```bash
ecc workspace create --directory gcd --pdk ics55 --pdk-root /path/to/icsprout55-pdk
```

The PDK root must point at an unpacked ICS55 PDK tree containing the expected
LEF and Liberty files.

### `TOP_NAME (workspace.design.top_module) not set`

Pass `Top module` through the parameters object:

```json
{
  "Design": "gcd",
  "Top module": "gcd",
  "Clock": "clk",
  "Frequency max [MHz]": 100
}
```

Then run with `--param-json params.json`, or include the same object as
`parameters` in `--input-json`.

### Command Does Not Use The Previous Workspace

Every command needs `--directory`. For example:

```bash
ecc workspace run-flow --directory gcd
ecc workspace get-home --directory gcd
```

The CLI does not persist a current workspace after `create` or `load`.
