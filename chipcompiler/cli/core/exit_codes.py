"""Stable coarse-grained CLI exit codes (extend_cli §6.2)."""

EXIT_SUCCESS = 0
EXIT_USAGE_ERROR = 2
EXIT_WORKSPACE_BUSY = 20
EXIT_REVISION_CONFLICT = 21
EXIT_PROCESS_NOT_RUNNING = 22
# In CLI contract 1 no ECC code path emits 23: the GUI-side contract gate
# (EccCliRuntimeService.ensureContract) emits it when the runtime, version
# schema, or cli_contract is unsupported, and the value stays reserved for
# ECC future use.
EXIT_CONTRACT_INCOMPATIBLE = 23
