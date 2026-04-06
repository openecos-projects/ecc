# ECC AGENTS

## Scope

- This file applies to all work under `workspaces/ecc/`.

## Common Commands

- Test: `pytest test/`
- Coverage: `pytest test/ --cov=chipcompiler --cov-report=term-missing`
- Format: `ruff format chipcompiler/ test/`
- Lint: `ruff check chipcompiler/ test/`
- Type check: `pyright chipcompiler/`
- Build ECC-Tools: `bazel build //chipcompiler/thirdparty:ecc_py_cmake`
- Build DreamPlace: `bazel build //chipcompiler/thirdparty:dreamplace_cmake`
- Install DreamPlace: `bazel run //bazel/scripts:install_dreamplace`
- Clean DreamPlace: `bazel run //bazel/scripts:clean_dreamplace`
- Prepare dev env: `bazel run //:prepare_dev`
