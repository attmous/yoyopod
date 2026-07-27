#!/usr/bin/env node
// Builds both public web properties and stages them for VPS upload:
//   www/                -> .artifacts/web/root/  (yoyopod.com)
//   docsite/website-vision/ -> .artifacts/web/docs/  (docs.yoyopod.com)
// Usage: node scripts/build_web.mjs [--no-install]
// See docs/operations/WEB_DEPLOY.md for the full deploy runbook.
import { spawnSync } from 'node:child_process';
import fs from 'node:fs';
import path from 'node:path';
import { fileURLToPath } from 'node:url';

const repoRoot = fileURLToPath(new URL('..', import.meta.url));
const skipInstall = process.argv.includes('--no-install');

const SITES = [
	{ dir: 'www', target: 'root' },
	{ dir: 'docsite/website-vision', target: 'docs' },
];

function run(args, cwd) {
	console.log(`\n> npm ${args.join(' ')}  (${path.relative(repoRoot, cwd) || '.'})`);
	// shell: true so npm.cmd resolves on Windows.
	const res = spawnSync('npm', args, { cwd, stdio: 'inherit', shell: true });
	if (res.status !== 0) {
		console.error(`npm ${args.join(' ')} failed in ${cwd} (exit ${res.status})`);
		process.exit(res.status ?? 1);
	}
}

const stage = path.join(repoRoot, '.artifacts', 'web');
fs.rmSync(stage, { recursive: true, force: true });

for (const site of SITES) {
	const cwd = path.join(repoRoot, site.dir);
	if (!skipInstall) run(['ci', '--no-fund', '--no-audit'], cwd);
	run(['run', 'build'], cwd);
	const dist = path.join(cwd, 'dist');
	const target = path.join(stage, site.target);
	fs.cpSync(dist, target, { recursive: true });
	console.log(`staged ${site.dir}/dist -> ${path.relative(repoRoot, target)}`);
}

console.log(`\nDone. Upload the contents of .artifacts/web/ per docs/operations/WEB_DEPLOY.md`);
