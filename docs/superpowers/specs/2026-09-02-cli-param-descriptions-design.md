# CLI Parameter Description Design

## Status

Approved design for completing `ecc param show <KEY>` descriptions for every
public parameter schema.

## Goal

Make `ecc param show` a useful, self-contained reference for the full reviewed
parameter registry. Every parameter must have a precise English description of
the setting that ECC applies, rather than a generated JSON-path placeholder.

## Scope

- Keep descriptions with their owning schema declarations: legacy parameters
  remain in `cli/project/params.py`; direct fields remain in their corresponding
  `cli/project/config_params/<step>.py` files; PDK paths remain in `pdk.py`.
- Use `docs/ecc-cli-config.en.md` as the wording reference for legacy and
  non-DreamPlace direct fields.
- For every exposed DreamPlace field, use the matching `description` in
  `chipcompiler/thirdparty/ecc-dreamplace/dreamplace/params.json`.
- Describe PDK fields in terms of their concrete PDK artifact and their path
  resolution relative to `pdk.root`.
- Preserve command output keys, formats, default values, and parameter names.

## Non-Goals

- Do not parse Markdown or DreamPlace metadata at CLI runtime.
- Do not expose additional workspace-owned paths or tool fields.
- Do not modify the user-provided English configuration reference as part of
  this change.

## Design

`config_param()` requires an explicit `description`; it no longer creates a
generic fallback. Each direct schema supplies a reviewable string next to its
field declaration. DreamPlace descriptions are kept explicitly in
`dreamplace.py`, matching upstream `params.json`, so the packaged CLI has no
runtime dependency on a source checkout.

The handler remains unchanged: `param_show()` resolves the schema value and
includes `schema.description` in its result record. Text and JSON renderers
therefore automatically display the enriched text.

## Validation

Tests assert that every registered schema has a non-empty description and that
no direct schema uses the removed generic fallback. A DreamPlace-specific test
loads the upstream JSON metadata and asserts that every exposed DreamPlace
schema description exactly matches its corresponding `description` value.

When a direct field is added, the schema declaration must provide a reviewed
description. When DreamPlace changes an exposed description, the test fails and
requires an explicit schema update.
