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
- The optional Rust scoring service is not part of this stack; the app renders everything from artifacts
  and simply omits the "served by rust" badge. To add it, run the root `docker-compose.yml` `serve`
  service alongside and set `FXRADAR_API_URL=http://serve:8080` in `deploy/.env`.
- Local test with Docker installed: `make docker` → http://localhost.
