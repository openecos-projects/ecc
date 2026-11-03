const fs = require('fs');

const manifestPath = 'signoff-artifacts/signoff_csv_manifest.json';

function sanitizeCell(value) {
  if (typeof value === 'number' && Number.isFinite(value)) return String(value);
  if (typeof value !== 'string') return '';
  return value
    .replace(/[\r\n]+/g, ' ')
    .replace(/`/g, "'")
    .replace(/\|/g, '/')
    .slice(0, 200);
}

function loadManifest() {
  if (!fs.existsSync(manifestPath)) return null;
  try {
    return JSON.parse(fs.readFileSync(manifestPath, 'utf8'));
  } catch {
    return null;
  }
}

function normalizeManifest(raw) {
  if (!raw || typeof raw !== 'object' || Array.isArray(raw)) return null;
  const checks = raw.checks;
  if (!checks || typeof checks !== 'object' || Array.isArray(checks)) return null;

  const normalizedChecks = Object.entries(checks)
    .filter(([, data]) => data && typeof data === 'object' && !Array.isArray(data))
    .map(([name, data]) => ({
      name: sanitizeCell(name),
      status: sanitizeCell(data.status || 'fail'),
      rows: sanitizeCell(data.rows ?? 0),
      file: sanitizeCell(data.file || ''),
    }));

  return {
    workspace: sanitizeCell(raw.workspace),
    design: sanitizeCell(raw.design || 'unknown'),
    gate: sanitizeCell(raw.gate || 'FAIL'),
    checks: normalizedChecks,
  };
}

function buildBody(manifest) {
  if (!manifest) {
    return '## Signoff CSV Report\n\nExport step failed before producing a manifest.\n';
  }

  const rows = manifest.checks
    .sort((a, b) => a.name.localeCompare(b.name))
    .map((check) => `| \`${check.name}\` | \`${check.status}\` | ${check.rows} | \`${check.file}\` |`)
    .join('\n');

  return [
    '## Signoff CSV Report',
    '',
    `- **Workspace**: \`${manifest.workspace}\``,
    `- **Design**: \`${manifest.design}\``,
    `- **Gate**: \`${manifest.gate}\``,
    '',
    '| Check | Status | Rows | CSV |',
    '| --- | --- | --- | --- |',
    rows,
    '',
  ].join('\n');
}

function main() {
  const summaryPath = process.env.GITHUB_STEP_SUMMARY;
  if (!summaryPath) {
    throw new Error('GITHUB_STEP_SUMMARY is not set');
  }

  const manifest = normalizeManifest(loadManifest());
  fs.appendFileSync(summaryPath, buildBody(manifest), 'utf8');
}

try {
  main();
} catch (error) {
  console.error(`signoff-csv-summary: ${error.message}`);
  process.exit(1);
}
