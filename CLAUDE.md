# CLAUDE.md

ECC is the EDA toolchain component of ECOS Studio, orchestrating EDA tools (Yosys, ECC-Tools, OpenROAD, Magic, KLayout) for RTL-to-GDS flows. The GUI and API server have been moved to `ecos/gui/` and `ecos/server/` respectively. See `docs/architecture.md` for architecture details and `docs/development.md` for workflows.

# Commands

```bash
# Setup
nix develop                              # recommended dev shell

# Test
pytest test/
pytest test/ --cov=chipcompiler --cov-report=term-missing

# Code quality
ruff format chipcompiler/ test/
ruff check chipcompiler/ test/
pyright chipcompiler/

# Bazel
bazel build //chipcompiler/thirdparty:ecc_py_cmake       # Build ECC-Tools
bazel run //bazel/scripts:install_dreamplace              # Build + install DreamPlace .so to source tree (via @ecc-dreamplace module)
bazel run //bazel/scripts:clean_dreamplace                # Remove installed DreamPlace artifacts
bazel run //bazel/scripts:prepare_dev                     # Full dev environment setup
```

# Workflow

`bazel run //:prepare_dev` performs: venv creation (`uv sync`) -> ECC-Tools runtime install -> DreamPlace `.so` install (built via `@ecc-dreamplace` module). After setup: `source .venv/bin/activate`. Use `--jobs=2` on memory-constrained machines.

## Integrating a Thirdparty Tool into the Build System

See [docs/development.md — Integrating a Thirdparty Tool into the Build System](docs/development.md#integrating-a-thirdparty-tool-into-the-build-system) for the full guide (dual-build strategy, Bazel targets, manifest-based install, pitfalls).

# Architecture

`services/` -> `rtl2gds/` -> `engine/` -> `tools/` -> `data/` -> `utility/`

All layers under `chipcompiler/`. GUI and API server are now maintained in `ecos/gui/` and `ecos/server/`.

# Gotchas

- ECC-Tools tool identifier in code is `"ecc"`, not `"ecc-tools"`. Wrapper: `chipcompiler/tools/ecc/`
- Every tool module must implement `is_eda_exist`, `build_step`, `run_step`
- Steps run in `multiprocessing.Process`; state persisted in `workspace.flow.json`
- File chaining: each step reads previous step's `output/`; first step uses `workspace.design.origin_verilog/origin_def`
- `uv.lock` is source of truth for Python deps; `requirements_lock.txt` is auto-generated and gitignored
- ECC runtime `.so` deps bundled via `scripts/autopatch-ecc-py.sh` (RPATH `$ORIGIN:$ORIGIN/lib`)
- Use `--config=ghproxy` for Bazel on restricted networks
- **Bazel 8 Bzlmod**: This project uses Bzlmod (`MODULE.bazel`), not legacy `WORKSPACE`. `new_local_repository` etc. must be loaded via `use_repo_rule()`, never used as bare globals. Do not use `WORKSPACE`-era idioms.
- **Do not assume Bazel/Starlark APIs exist** -- always verify against the exact Bazel version (currently 8.x) before using an API. For example, `watch_tree` has no `exclude` parameter. If an API doesn't work, investigate alternatives instead of retrying with guessed parameters.
