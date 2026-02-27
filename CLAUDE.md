# ECOS Chip Compiler (ECC)

ECOS chip design automation solution orchestrating EDA tools (Yosys, ECC-Tools, OpenROAD, Magic, KLayout) for RTL-to-GDS flows. See `docs/architecture.md` for architecture details and `docs/development.md` for workflows.

# Commands

```bash
# Setup
git submodule update --init --recursive  # required first-time
nix develop                              # recommended dev shell
bash ./build.sh                          # manual setup

# Test
pytest test/
pytest test/ --cov=chipcompiler --cov-report=term-missing

# Code quality
ruff format chipcompiler/ test/
ruff check chipcompiler/ test/
pyright chipcompiler/

# Run
chipcompiler --reload                    # API server dev mode, port 8765

# Bazel (release only)
bazel build //:release_bundle
bazel build //:api_server_bundle
bazel build //chipcompiler/thirdparty:ecc_py_cmake
```

# Architecture

`gui/` → `services/` → `rtl2gds/` → `engine/` → `tools/` → `data/` → `utility/`

All layers under `chipcompiler/`. GUI communicates with backend via REST on port 8765.

# Gotchas

- ECC-Tools tool identifier in code is `"ecc"`, not `"ecc-tools"`. Wrapper: `chipcompiler/tools/ecc/`
- Every tool module must implement `is_eda_exist`, `build_step`, `run_step`
- Steps run in `multiprocessing.Process`; state persisted in `workspace.flow.json`
- File chaining: each step reads previous step's `output/`; first step uses `workspace.design.origin_verilog/origin_def`
- `uv.lock` is source of truth for Python deps; `requirements_lock.txt` is auto-generated and gitignored
- ECC runtime `.so` deps bundled via `scripts/autopatch-ecc-py.sh` (RPATH `$ORIGIN:$ORIGIN/lib`)
- Use `--config=ghproxy` for Bazel on restricted networks
