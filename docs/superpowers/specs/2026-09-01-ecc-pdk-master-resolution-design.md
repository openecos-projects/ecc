# Fatal PDK Master Resolution Failures

## Goal

Stop an ECC flow as soon as its DEF or Verilog design input references a
cell or macro master that is absent from the loaded PDK LEF data. Every
unresolved master is fatal; there is no allowlist or black-box exception.

The user must see the input format, source file, instance name, and missing
master in the step log. The failed step must persist as `Incomplete`, and no
later flow step may run.

## Current Behavior

`DefRead::parse_component()` already returns `kDbFail` when it cannot resolve
a DEF component master. `DefRead::createDb()` returns `false` when the DEF
reader fails. ECC currently ignores that return value for normal flow steps
(the LVS path is the exception).

`VerilogRead::build_components()` logs an unresolved `cell_master` and
continues. Its callers, `createDb()` and `createDbAutoTop()`, consequently
return success with a partial database. The Python `ECCToolsModule.read_verilog`
wrapper also discards the native binding's boolean return value.

At the ECC boundary, `create_db_engine()` has a broad recovery path that can
retry design loading after an error, and `get_eda_instance()` turns an engine
creation exception into `None`. Neither behavior may hide a design-read
failure.

## Selected Design

Use the native parser return value as the only source of truth, then turn a
failed read into a non-recoverable ECC step exception. Do not add a separate
`ecc check` design parse: it would parse large designs twice and could diverge
from the database builder's master-resolution rules.

### ecc-tools Contract

Both `readDef()` and `readVerilog()` must return `false` when any instantiated
master is missing from the loaded LEF masters.

- DEF: retain the existing callback failure propagation for normal and gzip
  inputs. Add regression tests that prove the public `readDef()` result is
  `false` for an unresolved component master.
- Verilog: make `build_components()` report failure rather than skip the
  instance and report success. Propagate that result from both `createDb()`
  and `createDbAutoTop()`.
- Diagnostic: emit a fatal parser diagnostic with the input kind and path,
  the instance name, and the missing master name. The native API remains a
  boolean API; callers must not infer failure by matching log text.
- A failed parse must not be exposed as a usable database. The ECC caller
  discards the locally created module on failure, so partially built data
  cannot become an engine for a later operation.

### ECC Contract

`ECCToolsModule.read_def()` and `read_verilog()` both return `bool`.

`create_db_engine()` checks the result of the design-input read immediately.
On `false`, it raises a dedicated design-read exception whose message identifies
the format and source path and directs the user to the step log for the native
master diagnostic.

Recovery is limited to loading a serialized input DB:

- A missing or unreadable serialized DB may fall back once to DEF or Verilog.
- A DEF or Verilog read failure is terminal. It is neither retried nor converted
  to `None`.
- `get_eda_instance()` re-raises the design-read exception; it must not log and
  return `None` for this case.

The existing engine exception path is intentionally used. `execute_tool_step()`
records the exception, and `EngineFlow.run_step()` persists `Incomplete`
without calling output-based success detection. `run_steps()` then stops at
that state. This also prevents stale outputs from an earlier attempt from
making a failed parse appear successful.

## Flow Outcome

```text
DEF or Verilog input
        |
        v
ecc-tools resolves every instance master against loaded LEFs
        |
        +-- all found --> build DB --> run ECC operation
        |
        +-- any missing --> native read returns false
                                |
                                v
                         ECC raises design-read error
                                |
                                v
                  EngineFlow writes Incomplete and stops flow
```

No flow-state schema, PDK configuration field, command-line option, or
black-box escape hatch is introduced.

## Tests

1. Add ecc-tools unit coverage using a minimal LEF and a DEF whose component
   references an absent master; assert `readDef()` returns `false` for plain
   and gzip inputs.
2. Add ecc-tools unit coverage with a minimal Verilog top module that
   instantiates an absent master; assert `readVerilog()` returns `false`.
3. Add ECC runner tests for both false results. Assert that engine creation
   raises the design-read exception and that a failed design read is not
   retried as a fallback.
4. Add an EngineFlow regression test with a pre-existing required output.
   Make the ECC read raise the design-read exception, then assert the current
   step is `Incomplete`, its error is logged, and every following step remains
   unexecuted.
5. Preserve existing serialized-DB fallback coverage to prove that only
   database-load failures are recoverable.

## Alternatives Rejected

Parsing native logs in ECC is rejected because message wording is not an API
and cannot safely distinguish warnings from failures. A separate preflight
command is rejected because it duplicates parsing work and parser semantics.
