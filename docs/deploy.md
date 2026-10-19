# Deploying qa-agent

Operational facts verified on 2026-10-18 against host `hk-206`. Change this page in the same commit that changes the deployment, not afterwards.

## Host and paths

| Item | Value |
|---|---|
| Host | `206.187.213.212` (SSH alias `hk-206`), Ubuntu 24.04, 6 vCPU / 8 GB |
| Checkout | `/opt/qa-agent` |
| Python | 3.12.3 in `/opt/qa-agent/.venv` |
| Package | `nanobot_ai` 0.3.5, editable install (`_editable_impl_nanobot_ai.pth`) |
| Service | `/etc/systemd/system/qa-agent.service` |
| Config | `/root/.nanobot/config.json` |
| Data | `/root/.nanobot/` (`qa/qa.sqlite3`, `sessions/`, `logs/`, `workspace/`) |
| Reverse proxy | `/etc/nginx/conf.d/qa-agent.conf` |

The install is editable, so source edits under `/opt/qa-agent/nanobot/` take effect on service restart; there is no reinstall step.

## Ports

| Port | Bound by | Purpose |
|---|---|---|
| 8765 | `nanobot-gateway` on `127.0.0.1` | WebUI and `/api/*`; nginx proxies here |
| 18790 | `nanobot-gateway` on `127.0.0.1` | gateway port from `config.json` (`gateway.port`) |
| 8443 | nginx | public HTTPS entry, basic auth, `/api/` exempt |
| 80, 443 | nginx | other vhosts on this host, not qa-agent |

## Service unit

```ini
[Service]
User=root
WorkingDirectory=/opt/qa-agent
Environment=HOME=/root
Environment=PYTHONUNBUFFERED=1
ExecStart=/opt/qa-agent/.venv/bin/nanobot gateway --foreground
Restart=on-failure
RestartSec=5
```

`HOME=/root` matters: config and data resolve under `/root/.nanobot`, not under the checkout.

## Two artifacts git does not carry

A fresh clone is not a working deployment. Two paths are ignored by `.gitignore` and must be recreated:

| Path | Size | Rebuild |
|---|---|---|
| `.venv/` | ~270 MB | `python3 -m venv .venv && .venv/bin/pip install -e '.[dev]'` |
| `nanobot/web/dist/` | ~8.4 MB | `cd webui && npm install && npm run build` (vite writes to `../nanobot/web/dist` with `emptyOutDir: true`) |

Because `emptyOutDir` is true, a WebUI build wipes `nanobot/web/dist`. Never run it on a checkout that is currently serving traffic while sessions are mid-change; build in a worktree, then merge and restart.

`git clean -xdf` deletes both artifacts. Do not run it on the deployment checkout.

## Deploy a merged branch

```bash
cd /opt/qa-agent
git fetch --all
git merge --no-ff <branch>
.venv/bin/python -m pytest tests/qa -q      # gate; see STATUS.md for the current blocker
systemctl restart qa-agent
systemctl is-active qa-agent
curl -s -o /dev/null -w '%{http_code}\n' http://127.0.0.1:8765/   # expect 200
journalctl -u qa-agent -n 30 --no-pager
```

WebUI changes need `npm run build` in `webui/` *before* the restart; the gateway serves the built assets from `nanobot/web/dist`.

## Rollback

```bash
cd /opt/qa-agent
git log --oneline -5
git revert <sha>          # preferred: keeps history honest
# or, for a bad merge not yet depended on:
git reset --hard <good-sha>
systemctl restart qa-agent
```

Pre-git fallback: `/root/qa-agent-deploy.tar.gz` (2026-10-18 11:12) and `/root/dist-update.tgz`. Both are frozen snapshots that predate the repository; treat them as read-only emergency material and do not update them.

## Verification checklist

- `systemctl is-active qa-agent` returns `active`.
- `curl http://127.0.0.1:8765/` returns 200 and HTML.
- `journalctl -u qa-agent -n 50` shows no traceback.
- The QA workbench loads through nginx on 8443 (basic auth applies to `/`, not `/api/`).

## Known pitfalls

- The editable install records the entry points of whichever branch was installed last. A branch that changes `[project.entry-points]` therefore poisons the venv for other branches: `feat/qa-trace` adds `qa = qa_trace.cli:main` and a `pytest11` plugin, and switching to `main` without reinstalling leaves pytest importing a module that is not on that branch, so the gate dies with `ModuleNotFoundError: No module named 'qa_trace.pytest_plugin'`. After any branch switch that touches entry points, run `.venv/bin/pip install -e . --no-deps` before trusting the gate.
- The checkout is mode 777: any local process can write it. That is exactly why sessions must not share it.
- nginx applies basic auth on 8443 but exempts `/api/`; a 401 on the workbench is a proxy problem, not an app problem.
- `proxy_read_timeout` is 3600s for long agent runs; a hang beyond that is a proxy timeout, not a gateway crash.
- `ruff format` is forbidden by `AGENTS.md`; only `ruff check` is used.
