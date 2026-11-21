# AGENTS.md

This codebase is yours: its purpose and how it is built are up to you, and you will continue to build upon it.

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

For setup, testing, and code quality commands, see [docs/development.md](docs/development.md).

For integrating thirdparty tools, see [docs/development.md](docs/development.md#integrating-a-thirdparty-tool).

# Module Layout

- One concept, one package. Don't add prefixed sibling modules (`flow_*.py`, `workspace_*.py`,
  `step_*.py`); put the module in the concept's package under a short name (`flow/plan.py`, not `flow_plan.py`).
- Existing prefixed groups predate this rule: don't extend them; move the group into a package in its own refactor commit.
- A package's own `AGENTS.md` declares its scope and rules; update it when the scope changes. Package `AGENTS.md` files are excluded from the wheel and the bundle.

## Avoid Large Modules

- Prefer adding new modules instead of growing existing ones.
- If a file exceeds roughly 1000 LoC, add new functionality in a new module instead of extending the existing file unless there is a strong documented reason not to.
- This rule applies especially to high-touch files that already attract unrelated changes.
- When extracting code from a large module, move the related tests and module/type docs toward the new implementation so the invariants stay close to the code that owns them.

# Code Review

All code review in this repository MUST enforce [docs/review-guidelines.md](docs/review-guidelines.md): apply its "Non-Negotiable Additional Standards" and "Approval Bar" to every diff.
Findings that violate it are presumptive blockers.

# Gotchas

- ECC-Tools tool identifier in code is `"ecc"`, not `"ecc-tools"`. Wrapper: `chipcompiler/tools/ecc/`
- Step tool execution always runs in a one-shot subprocess worker, including frozen builds. The worker only reads what the parent gave it and only writes its own result; it never touches the flow ledger. See `chipcompiler/data/handshake/` and `chipcompiler/data/step/results.py` for the exact contract.
- Ignore Python 2 compatibility, this project uses Python 3+. You should not use the `__future__` module. If you need to worry about feature compatibility between different 3.xx point releases, check the closest pyproject.toml's requires-python field to see what minimum runtime version is supported.

## Simplicity First

- No features beyond what was asked. No abstractions for single-use code.
- No "flexibility" or "configurability" that wasn't requested.
- No error handling for impossible scenarios.
- If you write 200 lines and it could be 50, rewrite it.

## Test Structure and Fixtures

- Place tests near the ownership boundary they exercise. Tool-specific behavior belongs under `test/tools/<tool>/`; shared workspace/data behavior belongs under `test/data/`; CLI behavior belongs under `test/cli/`; cross-cutting invariants belong under `test/formal/`.
- Keep helper fixtures local to the narrowest useful scope, such as a tool test directory `conftest.py`, before promoting them to shared test fixtures.
- When tests need production defaults or tool config baselines, read the real template/config factory through a helper or fixture instead of duplicating default values. Keep literal values for explicit override inputs and assertions that intentionally define the default contract.
- Do not add tests for values that are statically defined.
- When writing tests, prefer comparing the equality of entire objects over fields one by one.
- Do not add negative tests for logic that was removed.
