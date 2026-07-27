# WEB_DEPLOY — publishing yoyopod.com and docs.yoyopod.com

How the two public web properties get built locally and uploaded to the VPS.

| Property | Source | Serves |
| --- | --- | --- |
| `https://yoyopod.com` | `www/` | marketing landing page |
| `https://docs.yoyopod.com` | `docsite/website-vision/` | public docs (vision site) |

Both are fully static Astro builds — no server-side code, no forms, no
databases. Deployment is: build locally, upload the files, done.

## Prerequisites

- **Node 22 LTS** on the build machine (Astro 7 requires `^20.19.0 || >=22.12.0`).
- SSH access to the VPS.
- DNS A/AAAA records for `yoyopod.com`, `www.yoyopod.com`, and
  `docs.yoyopod.com` pointing at the VPS.

## Build

From the repo root:

```bash
node scripts/build_web.mjs
```

Outputs land in `.artifacts/web/root/` (landing page) and
`.artifacts/web/docs/` (docs site). Pass `--no-install` to skip the `npm ci`
step on repeat builds.

## Upload — bash (Linux / WSL / Git Bash), preferred

```bash
rsync -avz --delete .artifacts/web/root/ deploy@VPS:/var/www/yoyopod.com/
rsync -avz --delete .artifacts/web/docs/ deploy@VPS:/var/www/docs.yoyopod.com/
```

## Upload — PowerShell (Windows OpenSSH)

`scp` on Windows has a verbatim-path quirk: `cd` into the artifact directory
first and use **relative paths**, plus the `-O` legacy-protocol flag. `scp`
cannot delete removed files, so stage on the server and swap with rsync
server-side:

```powershell
cd .artifacts\web
ssh deploy@VPS "rm -rf ~/web-upload && mkdir -p ~/web-upload"
scp -O -r root docs deploy@VPS:web-upload/
ssh deploy@VPS "sudo rsync -a --delete ~/web-upload/root/ /var/www/yoyopod.com/ && sudo rsync -a --delete ~/web-upload/docs/ /var/www/docs.yoyopod.com/"
```

## nginx

Two flat server blocks (certbot adds the 443 halves):

```nginx
server {
    server_name yoyopod.com www.yoyopod.com;
    root /var/www/yoyopod.com;
    index index.html;

    location / { try_files $uri $uri/ =404; }

    # Astro asset filenames are content-hashed -> safe to cache forever.
    location /_astro/ {
        expires 1y;
        add_header Cache-Control "public, immutable";
    }

    gzip on;
    gzip_types text/html text/css application/javascript image/svg+xml application/json;
}

server {
    server_name docs.yoyopod.com;
    root /var/www/docs.yoyopod.com;
    index index.html;

    location / { try_files $uri $uri/ =404; }
    error_page 404 /404.html;   # Starlight ships a 404.html

    location /_astro/ {
        expires 1y;
        add_header Cache-Control "public, immutable";
    }

    gzip on;
    gzip_types text/html text/css application/javascript image/svg+xml application/json;
}
```

HTML deliberately gets no long cache header — only `/_astro/` assets are
immutable.

The privacy page promises access logs are deleted after 14 days — make
logrotate keep that promise (`/etc/logrotate.d/nginx`: `daily` + `rotate 14`,
which is close to the Debian/Ubuntu default of `rotate 14`).

## Waitlist collector

The teaser page's "Notify me" form posts to `/api/notify` (configurable in
`www/src/consts.ts`). A dependency-free collector ships at
`www/server/notify-collector.mjs` — it appends `{email, ts}` JSON lines to
`/var/lib/yoyopod-waitlist/emails.jsonl`.

Install on the VPS:

```bash
sudo mkdir -p /opt/yoyopod-web /var/lib/yoyopod-waitlist
sudo cp notify-collector.mjs /opt/yoyopod-web/
sudo tee /etc/systemd/system/yoyopod-notify.service > /dev/null <<'EOF'
[Unit]
Description=yoyopod waitlist collector
After=network.target

[Service]
ExecStart=/usr/bin/node /opt/yoyopod-web/notify-collector.mjs
Environment=PORT=8787
Environment=DATA_FILE=/var/lib/yoyopod-waitlist/emails.jsonl
DynamicUser=yes
StateDirectory=yoyopod-waitlist
Restart=on-failure

[Install]
WantedBy=multi-user.target
EOF
sudo systemctl enable --now yoyopod-notify
```

Add to the `yoyopod.com` nginx server block (with a light rate limit; the
`limit_req_zone` line goes in the `http {}` context):

```nginx
# http {} context:
limit_req_zone $binary_remote_addr zone=notify:1m rate=6r/m;

# yoyopod.com server block:
location /api/notify {
    limit_req zone=notify burst=3 nodelay;
    proxy_pass http://127.0.0.1:8787;
    proxy_set_header X-Forwarded-For $remote_addr;
}
```

Check it: `curl -s -X POST https://yoyopod.com/api/notify -H 'Content-Type: application/json' -d '{"email":"test@example.com"}'` → `{"ok":true}`, then remove the test line from the data file.

Privacy: the file stores email + timestamp only, for a one-time availability
notification (stated next to the form and on `/privacy`). Honor erasure
requests by deleting the matching line. Prefer a hosted form service instead?
Point `NOTIFY_ENDPOINT` in `www/src/consts.ts` at its URL and skip this
section.

## TLS

One certificate with SANs, one renewal:

```bash
sudo certbot --nginx -d yoyopod.com -d www.yoyopod.com -d docs.yoyopod.com
```

Re-run with the extended `-d` list if a name is added later. Recommended:
add a `www.yoyopod.com -> yoyopod.com` 301 in the certbot-generated block.

## Verify after deploy

```bash
curl -sI https://yoyopod.com/ | head -1                     # 200
curl -sI https://yoyopod.com/imprint/ | head -1             # 200
curl -sI https://docs.yoyopod.com/ | head -1                # 200
curl -sI https://docs.yoyopod.com/nope/ | head -1           # 404
curl -sI https://docs.yoyopod.com/sitemap-index.xml | head -1
curl -sI "https://yoyopod.com$(curl -s https://yoyopod.com/ | grep -o '/_astro/[^\"]*\.css' | head -1)" | grep -i cache-control
```

## Related

- `www/README.md` — landing page dev commands and asset provenance.
- `docsite/website-vision/README.md` — docs site conventions.
- `.github/workflows/web.yml` — PR build check for both sites (build only,
  never deploys).
