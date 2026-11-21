# chipcompiler.engine.snapshot

Scope: the Engineering Snapshot — the committed, bounded summary of a workspace: writing and
reading its file, the projections and QoR facts it embeds, comparing two snapshots, and
exporting one.

## Rules

- The snapshot is bounded: project top-N shapes and artifact identity, never inline payload
  content or hash artifact files. Respect the size limits when adding a field.
- The workspace files stay authoritative; the snapshot is a projection of them. Comparison
  works on committed snapshot facts, never on live workspace contents.
- Snapshot QoR data is data-only; scoring belongs in `chipcompiler/analysis/qor/`.
- A persisted snapshot field is a compatibility surface: change its shape only with a schema
  version bump.
- `__init__.py` re-exports nothing.
- Tests: `test/engine/test_snapshot_<module>.py`.
