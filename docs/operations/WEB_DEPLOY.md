# WEB_DEPLOY — publishing yoyopod.com and docs.yoyopod.com

The two public properties are static Astro builds deployed together as one
immutable release:

| Property | Source | Release path |
| --- | --- | --- |
| `https://yoyopod.com` | `www/` | `root/` |
| `https://docs.yoyopod.com` | `docsite/website-vision/` | `docs/` |

Production lives below `/opt/yoyopod-web`. Each deploy extracts into a new
`releases/<release-id>/` directory and atomically switches the `current`
symlink. It never runs `rsync --delete` against a directory nginx is serving.
If post-switch checks fail, the installer restores the prior release.

## Current launch gate

Email collection is intentionally off:

- `www/src/consts.ts` has `NOTIFY_ENABLED = false`;
- the production nginx block returns `404` for `/api/notify`;
- `yoyopod-notify.service` is installed but not enabled.

Do not enable collection until the published contact mailbox works, Hetzner's
data processing agreement (AVV) is in place, the retention terms are final,
and the deployment has been reviewed for GDPR/DDG compliance.

## Build locally

Node 22 LTS is required for the Astro builds.

```bash
node scripts/build_web.mjs
```

The combined output is staged under:

```text
.artifacts/web/
├── root/   # yoyopod.com
└── docs/   # docs.yoyopod.com
```

Use `--no-install` only when both dependency trees are already current.

## First-time VPS bootstrap

The bootstrap is the only operation that changes nginx or systemd. It:

- creates the non-login `yoyopod-web-deploy` release owner;
- creates `/opt/yoyopod-web/releases`;
- installs only the YoYoPod nginx server blocks;
- installs the disabled waitlist service;
- grants the deploy user permission to restart only that service;
- installs a root-owned release installer and forced SSH command;
- runs `nginx -t` before reloading nginx.

On later runs, bootstrap detects Certbot-managed TLS directives in the live
YoYoPod vhost and preserves that file while still updating the installer,
forced command, service, and key restrictions. Reconcile any future changes
to the tracked HTTP template into the TLS-managed file explicitly, then run
`nginx -t` before reloading.

Generate a dedicated CI key outside the repository:

```bash
ssh-keygen -t ed25519 -f ~/.ssh/yoyopod_web_ci_ed25519 \
  -C github-actions-yoyopod-web
```

Upload `deploy/web/` plus the public key to a temporary directory, then run:

```bash
sudo bash deploy/web/bootstrap-vps.sh yoyopod_web_ci_ed25519.pub
```

Do not reuse a broad VPS root key in GitHub Actions. Bootstrap installs the
dedicated public key in root's `authorized_keys` with OpenSSH `restrict` and a
forced command. The key cannot obtain a shell, use forwarding, run SCP/SFTP, or
choose a program. It can only:

- stream a size-bounded YoYoPod archive into `/opt/yoyopod-web/incoming`;
- ask the fixed, root-owned installer to deploy that archive as the non-login
  release owner;
- report the installed installer hash and deployed commit.

This prevents the Actions credential from reading or modifying neighboring
sites even though they share the VPS.
Incoming archives abandoned for more than 60 minutes are pruned on the next
upload. The installer also holds `/opt/yoyopod-web/.deploy.lock` across the
entire atomic switch, health check, rollback, and metadata update, so manual
and Actions deployments cannot overlap. It retains five immutable releases,
always protecting both `current` and `previous`.

## Manual deployment from Windows

From a clean committed worktree:

```powershell
powershell.exe -NoProfile -File scripts/deploy_web.ps1 -SshTarget vps-root
```

The script builds both sites, writes the exact Git commit into the release,
creates one archive, uploads the archive and installer, and runs the installer
as `yoyopod-web-deploy`. To validate packaging without uploading:

```powershell
powershell.exe -NoProfile -File scripts/deploy_web.ps1 -DryRun
```

## GitHub Actions deployment

`.github/workflows/web-deploy.yml` is manual-only (`workflow_dispatch`). It:

1. resolves a full commit SHA;
2. proves the commit is reachable from `origin/main`;
3. checks out and builds both sites from that exact content commit with Node 22;
4. packages the collector and revision with the static output;
5. uses the current `main` deployment tooling to stream the archive through
   the forced-command key;
6. atomically installs and health-checks the release.

Configure the `production` GitHub environment with a deployment-branch policy
limited to `main` and these environment secrets:

| Secret | Value |
| --- | --- |
| `WEB_VPS_HOST` | VPS hostname or IP |
| `WEB_VPS_SSH_PRIVATE_KEY` | dedicated private key |
| `WEB_VPS_KNOWN_HOSTS` | pinned OpenSSH known-hosts line for the VPS |

Deploy the current `main` head from the Actions UI, or deploy an older exact
commit that is still reachable from `main`:

```bash
gh workflow run web-deploy.yml --ref main -f sha=<full-main-commit-sha>
```

The workflow uses a non-cancelling `web-production` concurrency group, so two
production releases cannot switch the symlink at the same time.
Historical rollback changes only the site content and bundled collector; the
workflow and pinned VPS installer always come from the current `main` head.

## nginx and TLS

The tracked HTTP configuration is `deploy/web/yoyopod.nginx.conf`. It serves:

```text
/opt/yoyopod-web/current/root
/opt/yoyopod-web/current/docs
```

Only content-hashed `/_astro/` assets receive immutable one-year caching.
HTML does not.

Before DNS changes, verify the VPS origin directly:

```bash
curl --resolve yoyopod.com:80:<vps-ip> http://yoyopod.com/
curl --resolve docs.yoyopod.com:80:<vps-ip> http://docs.yoyopod.com/
```

After the apex, `www`, and `docs` records point at the VPS, issue TLS:

```bash
sudo certbot --nginx \
  -d yoyopod.com \
  -d www.yoyopod.com \
  -d docs.yoyopod.com
```

Do not request the certificate before public DNS reaches this server.

## Verification

The remote installer checks all of these before accepting a release:

- `yoyopod.com/` → `200`;
- `yoyopod.com/imprint/` → `200`;
- `docs.yoyopod.com/` → `200`;
- a missing docs route → `404`;
- `yoyopod.com/api/notify` → `404` while collection is disabled, or a safe
  `GET` → `405` when the live nginx loopback proxy is deliberately enabled.

Before TLS, checks address the local HTTP vhost directly. Once Certbot
certificate directives exist, they address the local HTTPS vhost with SNI and
certificate validation. The checks never follow public DNS.

The privacy page promises access logs are deleted after 14 days. Keep
`/etc/logrotate.d/nginx` configured with `daily` and `rotate 14`; verify this
before every public cutover.

After DNS and TLS cutover, also verify:

```bash
curl -fsSI https://yoyopod.com/
curl -fsSI https://docs.yoyopod.com/
curl -sS -o /dev/null -w '%{http_code}\n' \
  https://docs.yoyopod.com/this-page-does-not-exist/
```

Re-check every pre-existing virtual host after nginx bootstrap and TLS changes.
Routine atomic releases do not reload nginx and therefore do not touch those
sites.

## Enabling email signup later

Treat this as a separate reviewed launch:

1. confirm `privacy@yoyopod.com` works and accept Hetzner's AVV;
2. set `NOTIFY_ENABLED = true`;
3. change the exact `/api/notify` nginx location to the rate-limited loopback
   proxy for `127.0.0.1:8787`;
4. enable and start `yoyopod-notify.service`;
5. run one test signup, verify the JSONL file, and remove the test record;
6. verify erasure and backup procedures before accepting real addresses.

The collector source is `www/server/notify-collector.mjs`; every release
already packages it at `/opt/yoyopod-web/current/notify-collector.mjs`.
