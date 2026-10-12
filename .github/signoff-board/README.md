# Signoff release kanban

Human-facing **diagram board** for signoff metrics. CSV / FileCheck gates stay
under `test/lit/csv_gates` as a util; this tree is what you attach to CI or a
GitHub Release so every catalog metric is visible as mermaid.

## Generate

From repo root (needs the signoff catalog on `PYTHONPATH`, i.e. this branch):

```bash
PYTHONPATH=. python .github/scripts/generate-signoff-kanban.py \
  --out .github/signoff-board/signoff-kanban.md
```

With a live / fixture assessment JSON (places cards into PASS/WARN/MISS/ERROR):

```bash
PYTHONPATH=. python .github/scripts/generate-signoff-kanban.py \
  --assessment /path/to/assessment.json \
  --out .github/signoff-board/signoff-kanban.md
```

## CI / release

Workflow `signoff-kanban.yml` uploads `signoff-kanban.md` as an artifact
(`signoff-release-kanban`). Open the markdown on GitHub to render mermaid.
