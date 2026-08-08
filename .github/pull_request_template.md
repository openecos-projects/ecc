## What Changed

- 

## Scope

Select the areas touched by this PR:

- [ ] CLI - command behavior, Typer command surface, output formats, or workspace commands.
- [ ] Flow/runtime - workspace lifecycle, EngineFlow, step execution, logs, metrics, or artifacts.
- [ ] EDA integration - Yosys, ECC-Tools, DreamPlace, KLayout, PDKs, or native/runtime wrappers.
- [ ] Build/package - Nix, PyInstaller, wheels, `uv.lock`, or release artifacts.
- [ ] CI/release - GitHub Actions, version checks, changelog, or release automation.
- [ ] Tests/docs only

## Runtime And Packaging Impact

- [ ] No runtime or packaging impact
- [ ] CLI output or machine-readable contract changed
- [ ] Workspace layout, flow state, or artifact paths changed
- [ ] Native toolchain or wrapper behavior changed
- [ ] `ecc-tools` or `ecc-dreamplace` dependency changed
- [ ] PyInstaller, Nix, or release artifact changed

Notes:

-


## Validation

List the commands you ran. Mark checks that are not applicable as N/A.

- [ ] `uv run pytest test/`
- [ ] `uv run ruff check chipcompiler test`
- [ ] `uv run ruff format --check chipcompiler test`
- [ ] PyInstaller smoke: `ecc --help`, `ecc --version`, `ecc version --json`
- [ ] Nix smoke: `nix run .#cli -- --help`
- [ ] Manual flow smoke:
- [ ] Other:

Skipped checks and reason:

-

## Checklist

- [ ] I kept the change scoped to ECC.
- [ ] I updated docs or user-facing CLI text where behavior changed.
- [ ] I included lockfile or version metadata updates when dependencies changed.
- [ ] I documented any submodule updates and why they are needed.
- [ ] I did not include local caches, virtual environments, or generated build outputs.
- [ ] I explained skipped validation and remaining risk.
