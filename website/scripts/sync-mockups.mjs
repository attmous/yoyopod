// Copies the normative UI mockups into the site's public/ dir so pages can
// iframe them. Canonical source stays at device/ui/assets/ui/ — re-run this
// (npm run sync:mockups) whenever the handoff package changes.
import { cp, mkdir, readdir } from 'node:fs/promises';
import { dirname, join } from 'node:path';
import { fileURLToPath } from 'node:url';

const here = dirname(fileURLToPath(import.meta.url));
const source = join(here, '..', '..', 'device', 'ui', 'assets', 'ui');
const target = join(here, '..', 'public', 'mockups');

await mkdir(target, { recursive: true });
const files = (await readdir(source)).filter(
	(f) => f.startsWith('mockup_') && f.endsWith('.html'),
);
for (const file of files) {
	await cp(join(source, file), join(target, file));
}
console.log(`Synced ${files.length} mockups -> public/mockups/`);
