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

async function main() {
  const token = process.env.GITHUB_TOKEN || process.env.GH_TOKEN;
  const repo = process.env.GITHUB_REPOSITORY;
  const issueNumber = process.env.PR_NUMBER;

  if (!issueNumber) {
    console.log('signoff-csv-notify: PR_NUMBER is empty; skipping');
    return;
  }
  if (!token || !repo) {
    throw new Error('missing GITHUB_TOKEN/GITHUB_REPOSITORY');
  }

  const apiUrl = process.env.GITHUB_API_URL || 'https://api.github.com';
  const headers = {
    Authorization: `Bearer ${token}`,
    Accept: 'application/vnd.github+json',
    'X-GitHub-Api-Version': '2022-11-28',
    'User-Agent': 'ecc-signoff-csv-notify',
  };

  const manifest = normalizeManifest(loadManifest());
  const body = buildBody(manifest);
  const createResponse = await fetch(`${apiUrl}/repos/${repo}/issues/${issueNumber}/comments`, {
    method: 'POST',
    headers,
    body: JSON.stringify({ body }),
  });
  if (!createResponse.ok) {
    throw new Error(`create comment failed: ${createResponse.status}`);
  }
}

main().catch((error) => {
  console.error(`signoff-csv-notify: ${error.message}`);
  process.exit(1);
});
