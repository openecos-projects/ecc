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
bazel build //chipcompiler/thirdparty:ecc_py_cmake
```

# Architecture

`services/` → `rtl2gds/` → `engine/` → `tools/` → `data/` → `utility/`

All layers under `chipcompiler/`. GUI and API server are now maintained in `ecos/gui/` and `ecos/server/`.

# Gotchas

- ECC-Tools tool identifier in code is `"ecc"`, not `"ecc-tools"`. Wrapper: `chipcompiler/tools/ecc/`
- Every tool module must implement `is_eda_exist`, `build_step`, `run_step`
- Steps run in `multiprocessing.Process`; state persisted in `workspace.flow.json`
- File chaining: each step reads previous step's `output/`; first step uses `workspace.design.origin_verilog/origin_def`
- `uv.lock` is source of truth for Python deps; `requirements_lock.txt` is auto-generated and gitignored
- ECC runtime `.so` deps bundled via `scripts/autopatch-ecc-py.sh` (RPATH `$ORIGIN:$ORIGIN/lib`)
- Use `--config=ghproxy` for Bazel on restricted networks
