# Draft — Material-based no-clock recognition

## Problem

`flow.no_clock` is a boolean flag. Reviewers asked for recognition from **design materials** (RTL / ports / parameters), not only the config switch. CTS skip already works when the flag is set (#207 / `c854efc`); remaining work is to **detect** clockless designs and drive the same skip policy safely.

## Intent

1. Infer whether a workspace/project is no-clock from materials:
   - empty / missing `clock` / `clock_port` parameter
   - RTL top has no clock-like port (heuristic or declared)
   - explicit `flow.no_clock` still wins when set
2. When inferred no-clock: fold CTS into skip set (same as today), keep virtual SDC path (#206).
3. When materials clearly have a clock port: do **not** skip CTS; require clock config as today.
4. Ambiguous cases: fail closed (require explicit `no_clock` or clock_port), with a clear error/probe message.

## Out of scope

- Signoff checklist `na_when` / observability (other worktree)
- ecc-tools virtual-clock tool bugs / version pins
- Local a13 shims
- PR merge ceremony unless asked

## Worktree

`/root/ec/ecc-no-clock-cts` branch `feat/no-clock-cts` (or a follow-up commit on that branch).

## Success signal

Unit tests cover: empty clock → no_clock effective; named clock port present → CTS required; explicit `no_clock=true` overrides; skip_steps CTS without no_clock still rejected; CLI/probe surfaces inferred vs explicit.
