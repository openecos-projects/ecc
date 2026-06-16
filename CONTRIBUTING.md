# Contributing to ECC

Thanks for contributing to ECOS Chip Compiler. ECC is the command-line and
Python toolchain component of ECOS Studio for RTL-to-GDS flows.

This guide covers contribution rules and review expectations. For setup,
builds, tests, and debug workflows, use the [Development Guide](docs/development.md).

## Repository Scope

- `chipcompiler/` - ECC Python package, CLI, flow runtime, tool wrappers, and packaging helpers.
- `test/` - Unit, CLI, runtime, integration-style, and formal tests.
- `nix/`, `flake.nix`, `flake.lock` - Nix packaging and development shell.
- `chipcompiler/thirdparty/` - Third-party source checkouts and generated/native integration points.
- `.github/` - CI, release, version checks, issue templates, and PR template.

Keep changes scoped to ECC. Do not mix unrelated CLI, runtime, packaging,
third-party, and CI changes in one PR unless they are required for one behavior
change.

## Development Setup

Use one of the setup paths in [docs/development.md](docs/development.md):

- `nix develop` for the optional Nix development shell.
- `uv sync --no-build-isolation-package ecc-dreamplace --no-binary-package ecc-tools-bin --verbose`
  for the ECC workspace.

`uv.lock` is the source of truth for Python dependency resolution. Do not
hand-edit lockfiles.

`ecc` is installed as an editable package. Source edits are picked up on the
next import.

## Branches And Commits

Use concise Conventional Commit-style subjects:

```text
feat(cli): add machine-readable status output
fix(runtime): initialize DB before workspace run-step
chore(build): update ecc-tools pin
docs: add contribution guide
ci: gate nix workflow paths
```

Prefer scopes that match the changed area: `cli`, `runtime`, `tools`, `build`,
`nix`, `ci`, or `docs`.

Install the local commit message hook before creating commits:

```sh
uv run prek install --config .pre-commit-config.yaml --hook-type commit-msg --overwrite
```

The hook uses `conventional-pre-commit` to check commit subjects against the
same Conventional Commit style.

## Pull Requests

Every PR should include:

- A short summary of the behavior, build, packaging, or documentation change.
- The affected area from the PR template.
- The exact validation commands that were run.
- Any skipped validation and the reason.
- Runtime or packaging impact, especially CLI output contracts, workspace layout,
  native wrappers, PyInstaller, Nix, or release artifacts.

If the PR changes a user-facing command, include before/after command examples or
output shape where useful. If the PR changes machine-readable output, describe
the contract change explicitly.

## Validation Expectations

Run the smallest checks that prove the change, then add broader checks when the
blast radius is larger.

- CLI command behavior: run focused CLI tests and include a command smoke such as
  `ecc --help`, `ecc --version`, or `ecc version --json` when relevant.
- Flow/runtime behavior: run focused tests for the touched step, workspace, or
  EngineFlow path; add a manual flow smoke when a valid PDK/workspace is needed
  and available.
- Python package changes: run relevant pytest coverage and Ruff checks for
  touched package/test paths.
- Native toolchain or wrapper changes: verify the wrapper path actually used at
  runtime, not only the low-level native module import.
- PyInstaller packaging changes: build the release artifact and smoke the
  resulting `ecc` binary with `--help`, `--version`, and `version --json`.
- Nix changes: verify the affected Nix output or explain why local Nix
  evaluation/build was not available.
- CI or release changes: validate YAML syntax and run the narrowest available
  workflow-specific check, such as `actionlint` when available.
- Documentation-only changes: proofread the updated docs and check links or
  command names against the current repository.

If a relevant check is skipped because it requires external PDK assets, network
access, a release wheel, or a specific host environment, state that plainly in
the PR.

## Dependencies, Versions, And Lockfiles

Keep dependency and version surfaces in sync:

- `pyproject.toml` and `uv.lock` for Python dependency changes.
- `flake.nix` and `flake.lock` for Nix input changes.
- Version metadata and release workflow inputs when changing release versions.

When a submodule bump suggests a dependency pin change, verify that the matching
wheel or release artifact exists before updating parent dependency metadata.

## Third-Party And Submodule Changes

Treat third-party repositories as separate projects:

- Commit fixes in the nested project first when the fix belongs there.
- Update the parent gitlink separately and document the new commit.
- Do not rely on unpublished local commits for merge-ready parent PRs.

## Generated Files

Do not commit local caches, virtual environments, generated build output, or
temporary workspaces. In particular, keep `.venv`, `.pytest_cache`,
`dist/`, generated release bundles, and local PDK/resource payloads out of
commits unless a file is intentionally part of a release or fixture.
