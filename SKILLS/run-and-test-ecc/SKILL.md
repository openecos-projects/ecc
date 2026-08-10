---
name: run-and-test-ecc
description: "Operate and verify this ECC checkout: prepare its Nix and uv editable environment, run project flows, resume or rerun an existing Workspace in place, repeat one persisted Step with --only and --force, choose focused Python/formal/integration tests, verify native import provenance, and report reproducible evidence. Use for ECC installation, builds, tests, flow runs, Workspace reproduction, one-Step tool development, and native-package readiness checks."
---

# Run and Test ECC

Use the live checkout as the source of truth. Verify the current CLI and Workspace contracts before reusing commands from an older branch or report.

## Establish the Checkout

1. Work from the repository root and read `AGENTS.md`, `docs/development.md`, and `pyproject.toml`.
2. Inspect `git status --short --branch` and `git submodule status --recursive`. Preserve unrelated dirt, local commits, and detached submodule state.
3. Treat a leading `-` in recursive submodule status as uninitialized. Do not call the native environment ready until required nested submodules are present.
4. When `.venv` exists, run:

```bash
.venv/bin/ecc --help
.venv/bin/ecc run --help
.venv/bin/ecc version
```

Treat this output and the current implementation as authoritative. Do not claim historical commands such as `metrics`, `artifacts`, `diagnose`, or a top-level `workspace` command unless the live help lists them.

## Prepare the Editable Environment

For a clean or intentionally realigned checkout, initialize the commits pinned by the parent repository before syncing. Run the sync inside the Nix environment without opening an interactive subshell:

```bash
git submodule sync --recursive
git submodule update --init --recursive --progress
nix develop --command uv sync \
  --no-build-isolation-package ecc-dreamplace \
  --no-build-isolation-package ecc-tools-bin \
  --verbose
```

If Nix is unavailable, run the same `uv sync` command directly. Use explicit `.venv/bin/*` commands afterward; shell activation is not required. Do not place commands after a bare `nix develop` in the same outer-shell batch because they run only after the interactive Nix shell exits.

Do not run `git submodule update` through dirty submodules without first protecting their changes. Do not use `--remote` unless the task explicitly asks to follow each submodule's remote branch instead of the parent gitlinks.

Verify the interpreter and actual native extensions, not only package metadata:

```bash
.venv/bin/python -c 'import sys; print(sys.executable)'
.venv/bin/python -c 'import torch; print(torch.__version__, torch.__file__)'
.venv/bin/python -c 'import dreamplace; print(dreamplace.__file__)'
.venv/bin/python -c 'from ecc_tools_bin import ecc_py; print(ecc_py.__file__)'
```

An `ecc version` result or successful `import ecc_tools_bin` does not prove that `ecc_py.so` loads. Diagnose editable rebuild failures, missing nested dependencies, stale build trees, GLIBC/ABI errors, and source-versus-installed version drift separately.

Apply this rebuild boundary:

- Python-only ECC edit: restart the Python process; ECC is editable.
- C/C++/CUDA edit: rebuild the affected configured target or reinstall that editable package.
- Build metadata, dependency, ABI, interpreter, or submodule change: rerun `uv sync`; use `--reinstall-package ecc-dreamplace` or `--reinstall-package ecc-tools-bin` when needed.
- Wheel: build only for delivery, release, or wheel-specific integration validation.

## Run a Project

Use the public CLI for a project containing `ecc.toml`:

```bash
.venv/bin/ecc init gcd
.venv/bin/ecc check --project /path/to/project
.venv/bin/ecc run --project /path/to/project
.venv/bin/ecc status --project /path/to/project
.venv/bin/ecc log --project /path/to/project
.venv/bin/ecc config --resolved --project /path/to/project
```

Use `nix run . -- <command>` to test the packaged Nix entry. Use `--overwrite` only when intentionally replacing an existing ECC run directory. Use repeatable `--set key=value` only in project mode.

## Reuse an Existing Workspace

List persisted Step names, tools, and states before selecting a Step:

```bash
jq -r '.steps[] | [.name, .tool, .state] | @tsv' \
  /path/to/workspace/home/flow.json
```

Use the public Workspace entry in place:

```bash
workspace=/path/to/workspace

# Re-execute one Step even when it is already Success.
.venv/bin/ecc run --workspace "$workspace" --only place --force

# Continue from the first non-Success Step.
.venv/bin/ecc run --workspace "$workspace" --resume

# Re-execute one Step and its persisted suffix.
.venv/bin/ecc run --workspace "$workspace" --from place
```

The common `rtl2gds` preset currently uses:

```text
Synthesis
Floorplan
fixFanout
place
CTS
legalization
route
drc
filler
```

`rcx` appends `RCX` and `sta`; `harden` appends `Harden`. Always prefer the reported Workspace's `home/flow.json`, which may contain a custom sequence.

Enforce these contracts:

- `--resume`, `--from`, and `--only` are mutually exclusive.
- Omitting a selector in Workspace mode is equivalent to `--resume`.
- `--force` is valid only with `--only`; without it, a successful Step is a no-op.
- Workspace mode cannot be combined with `--project`, `--run-id`, `--overwrite`, or `--set`.
- Workspace mode loads and mutates the Workspace in place; it does not create or copy one.
- Re-execution deletes the selected Step's current `output/`. A failed rerun does not restore it.
- Starting from an upstream Step invalidates persisted runtime/state for its suffix before execution.
- Tool builders may regenerate `config/*.json` from `home/parameters.json` and current Step paths. Inspect the live builder before relying on manual generated-config edits.
- ECC provides no Workspace process lock. Confirm that no second writer is active.

Use `--json` or `--jsonl` for machine-readable evidence. The current Workspace result contract uses `status`, `executed_steps`, and `no_op`; failures also use `failed_step` and `resume_cmd`. Do not claim `reused_steps`, `stale_steps`, or a top-level `state` field unless the implementation adds them.

For Python-level stepping with the same command contract:

```bash
.venv/bin/python -m chipcompiler.cli.main run \
  --workspace "$workspace" --only place --force --json
```

## Inspect Before Running

1. Read `home/flow.json` and identify the exact Step, tool, state, and predecessor.
2. Inspect the Step's `input/`, `output/`, `data/`, `feature/`, configs, and logs.
3. Verify absolute PDK, DEF, Verilog, SPEF, and external-tool paths embedded in the Workspace.
4. Confirm required inputs, including accepted `.gz` alternatives.
5. Record the command, environment variables, parent commit, recursive submodule commits, and observed failure before changing the artifact.

Do not silently copy a reported Workspace. Request authorization when the original must remain immutable and a copy is needed.

## Choose Tests by Ownership

Start narrow and widen according to risk:

```bash
# CLI and Workspace selectors
.venv/bin/python -m pytest test/cli/test_typer_cli.py test/cli/commands -q
.venv/bin/python -m pytest test/test_engine_rerun.py -q

# Tool wrapper
.venv/bin/python -m pytest test/tools/ecc/test_runner.py -q

# Cross-cutting contracts
.venv/bin/python -m pytest test/formal/ -q

# Full Python suite
.venv/bin/python -m pytest test/ -q
```

For the real ICS55 GCD integration, verify Yosys with the slang plugin, the PDK, and the external Sizer. Set `CHIPCOMPILER_OSS_CAD_DIR` when selecting an OSS CAD Suite instead of a `yosys` already available on `PATH`:

```bash
export CHIPCOMPILER_OSS_CAD_DIR=/path/to/oss-cad-suite
export CHIPCOMPILER_ICS55_PDK_ROOT=/path/to/ics55-pdk
export PATH=/path/to/ecc-sizer/build/src:$PATH
.venv/bin/python - <<'PY'
import os
import sys

from chipcompiler.tools.yosys.utility import check_slang_plugin, get_yosys_runtime

yosys_cmd, yosys_env = get_yosys_runtime()
if not yosys_cmd:
    raise SystemExit("Yosys is unavailable")
if not check_slang_plugin(yosys_cmd, os.getcwd(), yosys_env, sys.stdout):
    raise SystemExit("Yosys slang plugin is unavailable")
print(f"Yosys: {yosys_cmd[0]}")
PY
command -v Sizer
.venv/bin/python -m pytest \
  test/integration/test_rtl2gds_flow.py::test_ics55_gcd -q -s
```

Do not treat mocked CLI tests as native-flow proof, and do not run a full physical flow when a focused selector, parser, or wrapper test proves the requested behavior.

## Report Completion

Report separately:

- Checkout and recursive submodule provenance.
- Environment, interpreter, and imported native-extension provenance.
- Focused tests and exact node IDs or test files.
- Integration/full-flow status, including prerequisites not exercised.
- Workspace Steps executed, skipped as no-op, failed, or invalidated.
- Files, configs, and outputs changed during reproduction.
- Remaining native-build, PDK, license, or external-tool risks.

Never collapse configured, compiled, imported, unit-tested, and full-flow-validated into one claim.
