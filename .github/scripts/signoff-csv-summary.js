const fs = require('fs');

const artifactRoot = 'signoff-artifacts';
const artifactPrefix = 'e2e-signoff-csv-';

function sanitizeCell(value) {
  if (typeof value === 'number' && Number.isFinite(value)) return String(value);
  if (typeof value !== 'string') return '';
  return value
    .replace(/[\r\n]+/g, ' ')
    .replace(/`/g, "'")
    .replace(/\|/g, '/')
    .slice(0, 200);
}

function sanitizeHtml(value) {
  return sanitizeCell(value)
    .replace(/&/g, '&amp;')
    .replace(/</g, '&lt;')
    .replace(/>/g, '&gt;');
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

function readCsv(directory, file) {
  const path = `${directory}/${file}`;
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

function loadManifest(directory) {
  const path = `${directory}/signoff_csv_manifest.json`;
  if (!fs.existsSync(path)) return null;
  try {
    return JSON.parse(fs.readFileSync(path, 'utf8'));
  } catch {
    return null;
  }
}

function normalizeManifest(raw) {
  if (!raw || typeof raw !== 'object' || Array.isArray(raw)) return null;
  if (raw.schema_version !== 1) return null;
  if (raw.kind !== 'signoff_csv_manifest') return null;
  if (!['PASS', 'FAIL', 'ERROR'].includes(raw.gate)) return null;

  const checks = raw.checks;
  if (!checks || typeof checks !== 'object' || Array.isArray(checks)) return null;

  return { gate: sanitizeCell(raw.gate) };
}

function formatValue(row) {
  if (!row) return 'N/A';
  const value = sanitizeCell(row.value);
  if (!value) return 'N/A';
  const unit = sanitizeCell(row.unit);
  return `\`${value}\`${unit ? ` ${unit}` : ''}`;
}

function findMetric(rows, metric, kind) {
  return rows.find((row) => row.metric === metric && (!kind || row.kind === kind));
}

function findDieArea(rows) {
  return (
    rows.find((row) => row.metric === 'die_area' && row.step === 'Harden' && row.value) ||
    rows.find((row) => row.metric === 'die_area' && row.value)
  );
}

function buildAreaSection(rows) {
  const lines = ['#### Area', ''];
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

function buildStaSection(rows) {
  const selectedMetrics = new Set(['setup_wns', 'setup_tns', 'hold_wns', 'hold_tns']);
  const corners = new Map();

  for (const row of rows) {
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

  const lines = ['#### STA', ''];
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

function loadReport(design) {
  const directory = `${artifactRoot}/${artifactPrefix}${design}`;
  return {
    design,
    manifest: normalizeManifest(loadManifest(directory)),
    area: readCsv(directory, 'area.csv'),
    drc: readCsv(directory, 'drc.csv'),
    sta: readCsv(directory, 'sta.csv'),
  };
}

function buildOverviewRow(report) {
  const gate = report.manifest ? `\`${report.manifest.gate}\`` : '`Unavailable`';
  return (
    `| \`${sanitizeCell(report.design)}\` | ${gate} | ` +
    `${formatValue(findMetric(report.drc, 'drc_count'))} | ${formatValue(findDieArea(report.area))} | ` +
    `${formatValue(findMetric(report.sta, 'sta_setup_wns', 'qor_metrics'))} | ` +
    `${formatValue(findMetric(report.sta, 'sta_setup_tns', 'qor_metrics'))} | ` +
    `${formatValue(findMetric(report.sta, 'sta_hold_wns', 'qor_metrics'))} | ` +
    `${formatValue(findMetric(report.sta, 'sta_hold_tns', 'qor_metrics'))} |`
  );
}

function buildDesignDetails(report) {
  const lines = ['<details>', `<summary>${sanitizeHtml(report.design)}</summary>`, ''];
  const hasData = report.manifest || report.area.length || report.drc.length || report.sta.length;
  if (!hasData) {
    lines.push('No CSV artifact was produced by this E2E job.', '', '</details>', '');
    return lines;
  }

  lines.push(...buildAreaSection(report.area), ...buildStaSection(report.sta), '</details>', '');
  return lines;
}

function buildBody(reports) {
  if (!reports.length) {
    return '## Signoff CSV Report\n\nNo E2E design results were available.\n';
  }

  return [
    '## Signoff CSV Report',
    '',
    '| Design | Gate | DRC | Die area | Setup WNS | Setup TNS | Hold WNS | Hold TNS |',
    '| --- | --- | --- | --- | --- | --- | --- | --- |',
    ...reports.map(buildOverviewRow),
    '',
    ...reports.flatMap(buildDesignDetails),
  ].join('\n');
}

function expectedDesigns() {
  const raw = process.env.EXPECTED_DESIGNS;
  if (!raw) throw new Error('EXPECTED_DESIGNS is not set');
  const designs = JSON.parse(raw);
  if (
    !Array.isArray(designs) ||
    designs.some((design) => typeof design !== 'string' || !/^[A-Za-z0-9_.-]+$/.test(design))
  ) {
    throw new Error('EXPECTED_DESIGNS must be a JSON array of valid design names');
  }
  return designs;
}

function main() {
  const summaryPath = process.env.GITHUB_STEP_SUMMARY;
  if (!summaryPath) {
    throw new Error('GITHUB_STEP_SUMMARY is not set');
  }

  const reports = expectedDesigns().map(loadReport);
  fs.appendFileSync(summaryPath, buildBody(reports), 'utf8');
}

try {
  main();
} catch (error) {
  console.error(`signoff-csv-summary: ${error.message}`);
  process.exit(1);
}
