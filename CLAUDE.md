# CLAUDE.md

ECC is the EDA toolchain component of ECOS Studio, orchestrating EDA tools (Yosys, ECC-Tools, OpenROAD, Magic, KLayout) for RTL-to-GDS flows. See `docs/architecture.md` for architecture details and `docs/development.md` for workflows.

For setup, testing, code quality, and Bazel commands, see [docs/development.md](docs/development.md).

# Workflow

`bazel run //:prepare_dev` performs: venv creation (`uv sync`) -> ECC-Tools runtime install -> DreamPlace `.so` install (built via `@ecc-dreamplace` module). After setup: `source .venv/bin/activate`. Use `--jobs=1` on memory-constrained machines.

Release builds download a pre-built DreamPlace wheel from GitHub Releases instead of building from source. The CI workflow uses `uv pip install --no-deps <wheel-url>` directly.

For integrating thirdparty tools into the build system, see [docs/development.md](docs/development.md#integrating-a-thirdparty-tool-into-the-build-system).

# Gotchas

- ECC-Tools tool identifier in code is `"ecc"`, not `"ecc-tools"`. Wrapper: `chipcompiler/tools/ecc/`
- Every tool module must implement `is_eda_exist`, `build_step`, `run_step`
- Steps run in `multiprocessing.Process`; state persisted in `workspace.flow.json`
- File chaining: each step reads previous step's `output/`; first step uses `workspace.design.origin_verilog/origin_def`
- `uv.lock` is source of truth for Python deps; `requirements_lock.txt` is auto-generated and gitignored
- Use `--config=ghproxy` for Bazel on restricted networks
- **Bazel 8 Bzlmod**: This project uses Bzlmod (`MODULE.bazel`), not legacy `WORKSPACE`. `new_local_repository` etc. must be loaded via `use_repo_rule()`, never used as bare globals. Do not use `WORKSPACE`-era idioms.
- **Do not assume Bazel/Starlark APIs exist** -- always verify against the exact Bazel version (currently 8.x) before using an API. For example, `watch_tree` has no `exclude` parameter. If an API doesn't work, investigate alternatives instead of retrying with guessed parameters.

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
