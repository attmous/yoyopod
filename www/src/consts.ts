export const SITE_URL = 'https://yoyopod.com';
export const DOCS_URL = 'https://docs.yoyopod.com';
export const GITHUB_URL = 'https://github.com/attmous/yoyopod';
export const AGE_RANGE = '7–14';

// Where the waitlist form posts. Same-origin path proxied by nginx to the
// collector (docs/operations/WEB_DEPLOY.md § Waitlist collector); swap in a
// hosted form endpoint (Formspree etc.) here if preferred.
export const NOTIFY_ENDPOINT = '/api/notify';
// Keep collection closed until the contact mailbox, hosting AVV, and retention
// procedure are ready. The production nginx config also returns 404 here.
export const NOTIFY_ENABLED = false;

export const SITE_TITLE = 'yoyopod: the first device before a smartphone';
export const SITE_DESCRIPTION =
	'yoyopod is a parent-managed companion device for kids ages 7–14, built for safe communication, live location, and everyday audio without the distraction, complexity, or screen addiction of a smartphone.';
