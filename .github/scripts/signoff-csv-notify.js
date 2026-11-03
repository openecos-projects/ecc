const fs = require('fs');

const marker = '<!-- ecc-signoff-csv-report -->';
const manifestPath = 'signoff-artifacts/signoff_csv_manifest.json';

function buildBody() {
  let body = `## Signoff CSV Report\n\nExport step failed before producing a manifest.\n\n${marker}\n`;
  if (fs.existsSync(manifestPath)) {
    const manifest = JSON.parse(fs.readFileSync(manifestPath, 'utf8'));
    const rows = Object.entries(manifest.checks || {})
      .sort(([a], [b]) => a.localeCompare(b))
      .map(([name, data]) =>
        `| \`${name}\` | \`${data.status || 'fail'}\` | ${data.rows || 0} | \`${data.file || ''}\` |`
      )
      .join('\n');
    body = [
      '## Signoff CSV Report',
      '',
      `- **Workspace**: \`${manifest.workspace || ''}\``,
      `- **Design**: \`${manifest.design || 'unknown'}\``,
      `- **Gate**: \`${manifest.gate || 'FAIL'}\``,
      '',
      '| Check | Status | Rows | CSV |',
      '| --- | --- | --- | --- |',
      rows,
      '',
      marker,
      ''
    ].join('\n');
  }
  return body;
}

async function main() {
  const token = process.env.GITHUB_TOKEN || process.env.GH_TOKEN;
  const repo = process.env.GITHUB_REPOSITORY;
  const issueNumber = process.env.PR_NUMBER;
  if (!token || !repo || !issueNumber) {
    console.error('signoff-csv-notify: missing GITHUB_TOKEN/GITHUB_REPOSITORY/PR_NUMBER');
    process.exit(1);
  }

  const apiUrl = process.env.GITHUB_API_URL || 'https://api.github.com';
  const headers = {
    'Authorization': `Bearer ${token}`,
    'Accept': 'application/vnd.github+json',
    'X-GitHub-Api-Version': '2022-11-28',
    'User-Agent': 'ecc-signoff-csv-notify'
  };

  async function findExistingComment() {
    let page = 1;
    while (true) {
      const listUrl = `${apiUrl}/repos/${repo}/issues/${issueNumber}/comments?per_page=100&page=${page}`;
      const listResponse = await fetch(listUrl, { headers });
      if (!listResponse.ok) {
        throw new Error(`list comments failed: ${listResponse.status}`);
      }
      const comments = await listResponse.json();
      const existing = comments.find(
        (comment) => comment.user && comment.user.login === 'github-actions[bot]' && comment.body.includes(marker)
      );
      if (existing) return existing;
      const link = listResponse.headers.get('link') || '';
      if (!link.includes('rel="next"')) return null;
      page += 1;
    }
  }

  const existing = await findExistingComment();
  const body = buildBody();
  if (existing) {
    const updateResponse = await fetch(`${apiUrl}/repos/${repo}/issues/comments/${existing.id}`, {
      method: 'PATCH',
      headers,
      body: JSON.stringify({ body })
    });
    if (!updateResponse.ok) {
      throw new Error(`update comment failed: ${updateResponse.status}`);
    }
  } else {
    const createResponse = await fetch(`${apiUrl}/repos/${repo}/issues/${issueNumber}/comments`, {
      method: 'POST',
      headers,
      body: JSON.stringify({ body })
    });
    if (!createResponse.ok) {
      throw new Error(`create comment failed: ${createResponse.status}`);
    }
  }
}

main().catch((error) => {
  console.error(`signoff-csv-notify: ${error.message}`);
  process.exit(0);
});
