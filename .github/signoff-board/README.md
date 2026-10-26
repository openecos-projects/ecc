# Signoff release board

Generate from catalog (and optional assessment). Do not check in generated markdown.

```bash
PYTHONPATH=. python .github/scripts/generate-signoff-kanban.py \
  --out .github/signoff-board/signoff-kanban.md

PYTHONPATH=. python .github/scripts/generate-signoff-kanban.py \
  --assessment /path/to/assessment.json \
  --out .github/signoff-board/signoff-kanban.md
```
