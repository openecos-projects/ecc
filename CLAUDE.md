# CLAUDE.md

ECC is the EDA toolchain component of ECOS Studio, orchestrating EDA tools (Yosys, ECC-Tools, OpenROAD, Magic, KLayout) for RTL-to-GDS flows. See `docs/architecture.md` for architecture details and `docs/development.md` for workflows.

For setup, testing, and code quality commands, see [docs/development.md](docs/development.md).

# Workflow

If Nix is available, enter the dev shell before syncing:

```bash
nix develop
uv sync --no-build-isolation-package ecc-dreamplace --no-build-isolation-package ecc-tools-bin --verbose
source .venv/bin/activate
```

If Nix is not available, skip `nix develop` and run the `uv sync` command in the
normal shell. `ecc` is editable, so source changes are picked up on the next
import.

For integrating thirdparty tools, see [docs/development.md](docs/development.md#integrating-a-thirdparty-tool).

# Gotchas

- ECC-Tools tool identifier in code is `"ecc"`, not `"ecc-tools"`. Wrapper: `chipcompiler/tools/ecc/`
- Every tool module must implement `is_eda_exist`, `build_step`, `run_step`
- Steps run in `multiprocessing.Process`; state persisted in `workspace.flow.json`
- File chaining: each step reads previous step's `output/`; first step uses `workspace.design.origin_verilog/origin_def`
- `uv.lock` is source of truth for Python deps; `requirements_lock.txt` is auto-generated and gitignored

# Behavioral Guidelines

## 1. Think Before Coding

- State assumptions explicitly. If uncertain, ask.
- If multiple interpretations exist, present them — don't pick silently.
- If a simpler approach exists, say so. Push back when warranted.
- If something is unclear, stop and ask before implementing.

## 2. Simplicity First

- No features beyond what was asked. No abstractions for single-use code.
- No "flexibility" or "configurability" that wasn't requested.
- No error handling for impossible scenarios.
- If you write 200 lines and it could be 50, rewrite it.

## 3. Surgical Changes

- Touch only what you must. Don't "improve" adjacent code, comments, or formatting.
- Don't refactor things that aren't broken. Match existing style.
- Remove imports/variables/functions that YOUR changes made unused.
- Don't remove pre-existing dead code unless asked.
- Every changed line should trace directly to the user's request.

## 4. Goal-Driven Execution

- Transform tasks into verifiable goals.
- For multi-step tasks, state a brief plan with verification at each step.
- Loop independently with strong success criteria; ask for clarification when criteria are weak.
