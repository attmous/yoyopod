#!/usr/bin/env node
// Tiny waitlist collector for the yoyopod.com teaser page. Runs on the VPS
// behind nginx (location /api/notify → 127.0.0.1:8787) and appends one JSON
// line per signup to DATA_FILE. No dependencies.
//
// Install: docs/operations/WEB_DEPLOY.md § Waitlist collector.
// Privacy: stores email + timestamp only, for the single purpose of an
// ordering-availability notification. Delete a line to honor an erasure
// request; the file lives outside the webroot and is never served.
import http from 'node:http';
import fs from 'node:fs';
import path from 'node:path';

const PORT = Number(process.env.PORT ?? 8787);
const DATA_FILE = process.env.DATA_FILE ?? '/var/lib/yoyopod-waitlist/emails.jsonl';
const MAX_BODY = 4096;
const EMAIL_RE = /^[^\s@]+@[^\s@]+\.[^\s@]{2,}$/;

fs.mkdirSync(path.dirname(DATA_FILE), { recursive: true });

const server = http.createServer((req, res) => {
	if (req.method !== 'POST') {
		res.writeHead(405, { Allow: 'POST' }).end();
		return;
	}
	let body = '';
	req.on('data', (chunk) => {
		body += chunk;
		if (body.length > MAX_BODY) req.destroy();
	});
	req.on('end', () => {
		let email = '';
		const type = req.headers['content-type'] ?? '';
		try {
			if (type.includes('application/json')) {
				email = String(JSON.parse(body).email ?? '');
			} else {
				email = String(new URLSearchParams(body).get('email') ?? '');
			}
		} catch {
			/* fall through to validation */
		}
		email = email.trim().toLowerCase();
		if (!EMAIL_RE.test(email) || email.length > 254) {
			res.writeHead(400, { 'Content-Type': 'application/json' });
			res.end('{"ok":false}');
			return;
		}
		fs.appendFile(DATA_FILE, JSON.stringify({ email, ts: new Date().toISOString() }) + '\n', (err) => {
			if (err) {
				console.error('append failed:', err.message);
				res.writeHead(500, { 'Content-Type': 'application/json' });
				res.end('{"ok":false}');
				return;
			}
			// Form posts (no-JS fallback) get a human page; fetch gets JSON.
			if (type.includes('application/json')) {
				res.writeHead(200, { 'Content-Type': 'application/json' });
				res.end('{"ok":true}');
			} else {
				res.writeHead(200, { 'Content-Type': 'text/html; charset=utf-8' });
				res.end(
					'<!doctype html><meta name="viewport" content="width=device-width"><body style="background:#2b2836;color:#f0eee9;font-family:system-ui;display:grid;place-items:center;min-height:100vh;margin:0"><p>You’re on the list ✓ &nbsp;<a href="/" style="color:#05cae9">Back</a></p>'
				);
			}
		});
	});
});

server.listen(PORT, '127.0.0.1', () => {
	console.log(`notify-collector listening on 127.0.0.1:${PORT}, writing ${DATA_FILE}`);
});
