# ECC Candidate Execution Library

`agent/` contains deterministic candidate-flow execution and evidence
generation used by offline optimization tooling. It is a Python library, not a
network or stdio service, and it does not expose an ECC RPC entrypoint.

The package owns candidate workspace cloning, input binding, parameter
materialization, resumable candidate execution, foundation-data extraction,
and isolated native workers. Decisions remain in the higher-level ECOS Agent;
this package only validates bounded inputs and produces auditable artifacts.

Important boundaries:

- `operations.py` is private candidate execution coordination. It is not the
  GUI flow lifecycle; ordinary GUI flows use the ECC CLI process registry and
  Workspace `flow.json`.
- `runtime_support.py` contains the small Engine adapters shared by candidate
  workers. It has no transport concerns.
- `workspace_api.py` is a library facade retained for optimization callers;
  it is not mounted in a method registry or server.
- Candidate native steps run in separate worker processes because DREAMPlace,
  sizer, and log redirection have process-global state.
- All workspace paths, materialized configuration, receipts, and hashes remain
  validated before execution.

Run the focused test suite with:

```bash
uv run pytest agent/test
```
