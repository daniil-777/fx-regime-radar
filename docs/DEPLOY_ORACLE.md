# Always-on deploy: Docker on an Oracle Cloud "Always Free" VM

Streamlit Community Cloud sleeps idle apps; this path does not. One VM runs the app image behind
Caddy (automatic HTTPS when you have a domain), restarts with the host, and refreshes the artifacts
every weekday morning after the pipeline commit lands. Cost: €0 on the Always Free tier.

Files: [`deploy/Dockerfile`](../deploy/Dockerfile) (the app image), [`deploy/docker-compose.yml`](../deploy/docker-compose.yml)
(app + Caddy), [`deploy/Caddyfile`](../deploy/Caddyfile), [`deploy/refresh.sh`](../deploy/refresh.sh)
(pull → restart/rebuild), [`deploy/cloud-init.yaml`](../deploy/cloud-init.yaml) (first-boot script).
The GitHub Action `docker image` builds and health-checks the image on every relevant push.

## 1. Create the VM (≈ 5 minutes of clicking)

1. Sign up at https://cloud.oracle.com (Always Free needs a card for identity, it is not charged).
2. *Compute → Instances → Create instance.*
   - **Image:** Canonical Ubuntu 24.04 (pick the *aarch64* build for Ampere).
   - **Shape:** *Ampere → VM.Standard.A1.Flex*, 2 OCPU / 12 GB is plenty (Always Free allows up to 4 OCPU / 24 GB).
     If your region says "out of capacity" for A1, retry later, try another availability domain, or use
     the *VM.Standard.E2.1.Micro* (1 GB — works, but tight; keep only this stack on it).
   - **Networking:** create/use a VCN with a public subnet, *assign a public IPv4*.
   - **SSH keys:** upload or generate a key (you will want SSH for logs).
   - **Advanced options → Management → Cloud-init script:** paste `deploy/cloud-init.yaml`, after
     editing `SITE_ADDRESS` (leave `:80` if you have no domain yet) and, optionally, `ANTHROPIC_API_KEY`.
3. *Create.* Note the public IP.

## 2. Open the ports in Oracle's network (the step everyone forgets)

*Networking → Virtual cloud networks → your VCN → Security Lists → Default → Add Ingress Rules:*

| Source | Protocol | Dest. port | Purpose |
|---|---|---|---|
| 0.0.0.0/0 | TCP | 80 | HTTP (and Let's Encrypt validation) |
| 0.0.0.0/0 | TCP | 443 | HTTPS |

(The VM's own firewall is opened by cloud-init: Oracle's Ubuntu images ship an iptables REJECT rule,
and the script inserts ACCEPT rules for 80/443 in front of it and persists them.)

## 3. Wait, then open it

First boot installs Docker, clones the repo and builds the image: **5–10 minutes**. Then
`http://<public-ip>` shows the dashboard. To watch progress:

```bash
ssh ubuntu@<public-ip>
sudo tail -f /var/log/cloud-init-output.log        # until "fx-regime-radar is starting"
cd /opt/fx-regime-radar/deploy && docker compose ps  # both containers "healthy"/"running"
docker compose logs -f app                            # Streamlit log
```

## 4. HTTPS with a free domain (optional, 5 minutes)

1. Get a name: your own domain, or a free one at https://www.duckdns.org (`something.duckdns.org`)
   pointing at the public IP.
2. On the VM: `nano /opt/fx-regime-radar/deploy/.env` → `SITE_ADDRESS=something.duckdns.org`
3. `cd /opt/fx-regime-radar/deploy && docker compose up -d` — Caddy obtains and renews the
   certificate itself; `https://something.duckdns.org` works within a minute (port 80 must stay open).

## 5. How it stays fresh (nothing to do)

- The GitHub Action pipeline runs weekdays 06:00 UTC and commits new artifacts to `main`.
- Cron on the VM runs `deploy/refresh.sh` at 06:40 UTC weekdays: `git pull --ff-only`; if only
  `data/ models/ reports/` changed it restarts the app (2–3 s), if code changed it rebuilds the image.
  Log: `deploy/refresh.log`. Run it by hand any time: `/opt/fx-regime-radar/deploy/refresh.sh`.
- Docker's `restart: unless-stopped` + the Docker service starting at boot make it survive reboots
  and Oracle maintenance.

## 6. Everyday commands

```bash
cd /opt/fx-regime-radar/deploy
docker compose ps                  # status + health
docker compose logs --tail 100 app # recent app log
docker compose restart app         # after editing deploy/.env
docker compose up -d --build       # rebuild after code changes (refresh.sh does this for you)
docker compose down                # stop everything
```

## Notes

- The container runs as uid 1000 (`radar`), the same uid as Ubuntu's `ubuntu` user, so the bind-mounted
  `data/` (writable only for the arcade's local sqlite) has the right permissions.
- Rule 8 holds: the image only reads artifacts; the pipeline never runs on the VM.
- Secrets never enter the image or git: `deploy/.env` is gitignored and read at container start.
- The Rust scoring service is optional for the dashboard (the app renders everything from artifacts
  and simply omits the "served by rust" badge). To run it on the same VM see section 7; then set
  `FXRADAR_API_URL=http://127.0.0.1:8080` in `deploy/.env`.
- Local test with Docker installed: `make docker` → http://localhost.

## 7. The API service (phase 24): systemd + env-file

The productised `fxradar-serve` (keys, alerts, `/docs`, `/metrics`, widget — see
[`docs/API.md`](API.md)) runs best as a plain systemd unit next to the Docker stack: one static
binary, no Python, restarts with the host, and the sqlite key store stays on the VM's disk.

**Build once on the VM** (Ampere A1 builds the arm64 binary natively, ~10 min the first time):

```bash
curl --proto '=https' --tlsv1.2 -sSf https://sh.rustup.rs | sh -s -- -y && . ~/.cargo/env
cd /opt/fx-regime-radar/rust/fxradar-serve && cargo build --release
sudo install -m 0755 target/release/fxradar-serve target/release/keys target/release/selftest /usr/local/bin/
sudo install -d -o ubuntu -g ubuntu -m 0750 /var/lib/fxradar      # keys.db lives here, not in git
```

**Secrets in an env-file** (root-only, never in the repo):

```bash
sudo tee /etc/fxradar/serve.env >/dev/null <<'ENV'
FXRADAR_KEYS_DB=/var/lib/fxradar/keys.db
FXRADAR_RATE_LIMIT_PER_MIN=60
FXRADAR_ALERT_POLL_SECS=300
STRIPE_WEBHOOK_SECRET=whsec_replace_me_from_the_stripe_dashboard_test_mode
RUST_LOG=info,tower_http=info
ENV
sudo chmod 0600 /etc/fxradar/serve.env
```

**Unit** `/etc/systemd/system/fxradar-serve.service`:

```ini
[Unit]
Description=FX Regime Radar API (Rust, gated by the golden self-test)
After=network-online.target
Wants=network-online.target

[Service]
User=ubuntu
WorkingDirectory=/opt/fx-regime-radar
EnvironmentFile=/etc/fxradar/serve.env
ExecStart=/usr/local/bin/fxradar-serve --bundle models/bundle_v1.4.0 --data-dir data --bind 127.0.0.1:8080
Restart=on-failure
RestartSec=5
# the gate: if the bundle does not reproduce the goldens the process exits 1 and systemd stops retrying after 5 tries
StartLimitIntervalSec=300
StartLimitBurst=5
NoNewPrivileges=true
ProtectSystem=strict
ReadWritePaths=/var/lib/fxradar
ProtectHome=read-only

[Install]
WantedBy=multi-user.target
```

```bash
sudo systemctl daemon-reload && sudo systemctl enable --now fxradar-serve
journalctl -u fxradar-serve -f            # watch the golden table, then "listening"
curl -s http://127.0.0.1:8080/api/health  # the health check for everything below
```

**Expose it through Caddy** (so the API shares the HTTPS certificate; add to `deploy/Caddyfile`
inside the site block, then `docker compose up -d` — Caddy runs in the compose network, so it
reaches the host service via the Docker host gateway):

```
handle /api/* { reverse_proxy host.docker.internal:8080 }
handle /docs* { reverse_proxy host.docker.internal:8080 }
handle /api-docs/* { reverse_proxy host.docker.internal:8080 }
handle /metrics { reverse_proxy host.docker.internal:8080 }
handle /widget* { reverse_proxy host.docker.internal:8080 }
```
(`extra_hosts: ["host.docker.internal:host-gateway"]` on the caddy service in `deploy/docker-compose.yml`.)
Ports: the security list from section 2 (80/443) is all that is needed — 8080 stays bound to
127.0.0.1 and is never opened. Consider a Caddy `basic_auth` or IP allow-list on `/metrics`.

**Health checks**: `/api/health` (200 + `"selftest":{"status":"pass"}`) is the probe for systemd
watchdogs, Caddy `health_uri`, and uptime monitors. A 5xx or no answer means the gate refused or
the process is down — look at `journalctl -u fxradar-serve`.

**Issue the first key** (prints the plaintext once; hand it over out-of-band):

```bash
sudo -u ubuntu FXRADAR_KEYS_DB=/var/lib/fxradar/keys.db keys issue --label "design partner 1" --tier pro
keys list                      # same env var: hash prefix, tier, last used
keys set-tier <prefix> partner # or let the Stripe webhook do it
```

**Refresh**: `deploy/refresh.sh` pulls artifacts daily; the service re-reads `data/regimes.parquet`
when its mtime changes (no restart needed). After a *code* change: rebuild, `install`, then
`sudo systemctl restart fxradar-serve` — the gate runs again before the port is bound.
**Backup** `/var/lib/fxradar/keys.db` (it holds hashes, webhook secrets and alert state — treat
the backup as a secret too).
