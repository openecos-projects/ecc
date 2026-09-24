# Flow e2e lit suite

Black-box checks against workspaces produced by running **real designs**
through an `ecc` binary (typically the PyInstaller bundle). This suite only
checks — it never runs flows.

## Layout

Design data lives in an external designs directory — the canonical one is
[openecos-projects/ecc-ci-designs](https://github.com/openecos-projects/ecc-ci-designs).
Each design is a self-contained ECC project:

```
<designs-dir>/
  gcd/
    ecc.toml          # complete project config; [pdk] root left empty
    rtl/gcd.v
    checks/*.check    # FileCheck expectations (see below)
    gcd.lit           # this suite's test file
```

Adding a design is adding one such directory; no changes in this repo.

## Running

```bash
# 1. produce workspaces (parallel over designs)
nix/scripts/run_designs.sh --ecc <ecc-binary> --designs-dir <designs-dir> \
    [--design NAME ...] [--jobs N] [--out-root OUT] [--pdk-root DIR]

# 2. check the produced workspaces
ECC_E2E_DESIGNS=<designs-dir> ECC_FLOW_WORKSPACES=<out-root> \
    bash nix/scripts/signoff_lit.sh test/e2e
# or via Nix:
ECC_E2E_DESIGNS=... ECC_FLOW_WORKSPACES=... nix run .#signoff-lit -- test/e2e
```

`run_designs.sh` injects the PDK via `CHIPCOMPILER_ICS55_PDK_ROOT`
(`--pdk-root` > env > `../pdk/icsprout55-pdk`). Other tool runtimes
(`CHIPCOMPILER_OSS_CAD_DIR`, `CHIPCOMPILER_ECC_SIZER_ROOT`, …) come from the
caller's environment, exactly as for a manual `ecc run`.

A design's workspace is `<out-root>/<name>/default/`. Each `.lit` case starts
with `; REQUIRES: flow-<name>`; designs without a produced workspace show as
UNSUPPORTED, not FAIL.

## Writing checks

Pin structure, not numbers. Timestamps, runtimes and QoR values drift between
runs; assert the lines that must exist (`CHECK`), must not (`CHECK-NOT`), and
JSON state via `jq`:

```
; REQUIRES: flow-gcd
; RUN: %filecheck --input-file %flows/gcd/default/Synthesis_yosys/report/Synthesis_check.rpt %S/checks/synthesis.check
; RUN: %jq -e "[.steps[].state] | all(. == \"Success\")" %flows/gcd/default/home/flow.json
```

Substitutions: `%flows` (out-root), `%filecheck`, `%jq`.

## CI

The `e2e-packaged-flow` job in `.github/workflows/ci.yml` runs this against
the PyInstaller bundle. Multi-design CI parallelization (dynamic matrix over
the designs directory) is a planned follow-up.
