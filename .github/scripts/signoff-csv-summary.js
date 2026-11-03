const fs = require('fs');

const artifactDir = 'signoff-artifacts';
const manifestPath = `${artifactDir}/signoff_csv_manifest.json`;

function sanitizeCell(value) {
  if (typeof value === 'number' && Number.isFinite(value)) return String(value);
  if (typeof value !== 'string') return '';
  return value
    .replace(/[\r\n]+/g, ' ')
    .replace(/`/g, "'")
    .replace(/\|/g, '/')
    .slice(0, 200);
}

function parseCsv(text) {
  const rows = [];
  let row = [];
  let field = '';
  let quoted = false;

  for (let i = 0; i < text.length; i += 1) {
    const char = text[i];
    if (quoted) {
      if (char === '"') {
        if (text[i + 1] === '"') {
          field += '"';
          i += 1;
        } else {
          quoted = false;
        }
      } else {
        field += char;
      }
    } else if (char === '"' && field === '') {
      quoted = true;
    } else if (char === ',') {
      row.push(field);
      field = '';
    } else if (char === '\n') {
      row.push(field);
      rows.push(row);
      row = [];
      field = '';
    } else if (char !== '\r') {
      field += char;
    }
  }
  if (field || row.length) {
    row.push(field);
    rows.push(row);
  }
  return rows;
}

function readCsv(file) {
  const path = `${artifactDir}/${file}`;
  if (!fs.existsSync(path)) return [];
  try {
    const [headers = [], ...records] = parseCsv(fs.readFileSync(path, 'utf8'));
    return records
      .filter((record) => record.some((cell) => cell !== ''))
      .map((record) =>
        Object.fromEntries(headers.map((header, index) => [header, record[index] || '']))
      );
  } catch {
    return [];
  }
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
    design: sanitizeCell(raw.design || 'unknown'),
    gate: sanitizeCell(raw.gate || 'FAIL'),
    checks: normalizedChecks,
  };
}

function formatValue(row) {
  const value = sanitizeCell(row.value);
  if (!value) return 'N/A';
  const unit = sanitizeCell(row.unit);
  return `\`${value}\`${unit ? ` ${unit}` : ''}`;
}

function buildAreaSection() {
  const rows = readCsv('area.csv');
  const lines = ['### Area', ''];
  if (!rows.length) {
    lines.push('No area data available.', '');
    return lines;
  }
  lines.push(
    '| Step | Metric | Value |',
    '| --- | --- | --- |',
    ...rows.map(
      (row) =>
        `| \`${sanitizeCell(row.step)}\` | \`${sanitizeCell(row.metric)}\` | ${formatValue(row)} |`
    ),
    ''
  );
  return lines;
}

function buildDrcSection() {
  const row = readCsv('drc.csv').find((record) => record.metric === 'drc_count');
  return [
    '### DRC',
    '',
    row ? `- **DRC count**: ${formatValue(row)}` : 'No DRC data available.',
    '',
  ];
}

function buildStaSection() {
  const selectedMetrics = new Set(['setup_wns', 'setup_tns', 'hold_wns', 'hold_tns']);
  const corners = new Map();

  for (const row of readCsv('sta.csv')) {
    if (row.kind !== 'qor_metrics' && row.kind !== 'corner_summary') continue;
    const metric = row.kind === 'qor_metrics' ? row.metric.replace(/^sta_/, '') : row.metric;
    if (!selectedMetrics.has(metric)) continue;

    const corner = row.kind === 'qor_metrics' ? 'Overall' : row.corner;
    const rcCorner = row.kind === 'qor_metrics' ? '-' : row.rc_corner;
    const key = JSON.stringify([corner, rcCorner]);
    if (!corners.has(key)) {
      corners.set(key, { corner, rcCorner, values: {} });
    }
    corners.get(key).values[metric] = formatValue(row);
  }

  const lines = ['### STA', ''];
  if (!corners.size) {
    lines.push('No STA WNS/TNS data available.', '');
    return lines;
  }
  lines.push(
    '| Corner | RC corner | Setup WNS | Setup TNS | Hold WNS | Hold TNS |',
    '| --- | --- | --- | --- | --- | --- |',
    ...[...corners.values()].map(
      (entry) =>
        `| \`${sanitizeCell(entry.corner)}\` | \`${sanitizeCell(entry.rcCorner)}\` | ` +
        `${entry.values.setup_wns || 'N/A'} | ${entry.values.setup_tns || 'N/A'} | ` +
        `${entry.values.hold_wns || 'N/A'} | ${entry.values.hold_tns || 'N/A'} |`
    ),
    ''
  );
  return lines;
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
    `- **Design**: \`${manifest.design}\``,
    `- **Gate**: \`${manifest.gate}\``,
    '',
    '| Check | Status | Rows | CSV |',
    '| --- | --- | --- | --- |',
    rows,
    '',
    ...buildAreaSection(),
    ...buildDrcSection(),
    ...buildStaSection(),
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
