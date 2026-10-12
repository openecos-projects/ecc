# Signoff release board (导览)

Human **homepage guide** for signoff metrics: map → readiness swimlanes →
category tours → per-metric drill-down.

CSV / FileCheck under `test/lit/csv_gates` stays a **util** — this board is the
navigable artifact you open on GitHub or attach to a Release.

## Generate

```bash
PYTHONPATH=. python .github/scripts/generate-signoff-kanban.py \
  --out .github/signoff-board/signoff-kanban.md
```

Live swimlanes (PASS / WARN / MISS / ERROR):

```bash
PYTHONPATH=. python .github/scripts/generate-signoff-kanban.py \
  --assessment /path/to/assessment.json \
  --out .github/signoff-board/signoff-kanban.md
```

## What the homepage contains

1. **How to read** — tour flowchart  
2. **Catalog map** — domains (quality / artifact / flow / …)  
3. **Readiness board** — swimlane kanban  
4. **Categories** — table + diagram + links into metrics  
5. **Per-metric index** — one diagram each, with back-links  

Open `signoff-kanban.md` on GitHub to render mermaid.
