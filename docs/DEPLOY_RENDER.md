# Deploy: GitHub Pages + Render (the fast path)

Three public pieces, two hosts:

| piece | host | why |
|---|---|---|
| static customer surface (`public/`: overview, pairs, treasury, storms, proof) | GitHub Pages | plain HTML + `state.json`; free, CDN, no account beyond GitHub |
| AI presenter (`/avatar`) + scoring API — the Rust service | Render, `fxradar-presenter` | it runs the gated brain and holds the vendor keys, so it cannot be static |
| Streamlit console | Render, `fxradar-dashboard` | Python server |

The daily pipeline still runs in GitHub Actions and commits artifacts; nothing is computed on either
host (rule 8). After each successful `daily-refresh`, `.github/workflows/pages.yml` republishes the
static site and — if the `RENDER_DEPLOY_HOOKS` secret is set — redeploys the Render services, whose
images bake today's artifacts in.

## 1. GitHub Pages (once)

*Settings → Pages → Source: GitHub Actions* (or `gh api -X POST repos/<owner>/<repo>/pages -f build_type=workflow`),
then *Actions → pages → Run workflow*. The site is at `https://<owner>.github.io/<repo>/`.

## 2. Render (about five minutes)

1. Sign in at render.com with GitHub. *New → Blueprint*, pick this repository; Render reads
   `render.yaml` and proposes both services.
2. Paste the keys it asks for (each optional; leave blank to skip):
   - `ANAM_API_KEY` — photoreal face. **Without it, set `FXRADAR_AVATAR_VENDOR=local`** (drawn
     presenter), or every session start returns 503.
   - `ELEVENLABS_API_KEY` — studio voice (else the browser's voice).
   - `ANTHROPIC_API_KEY` — open conversation via Haiku (else the keyless FAQ answers).
   - `FXRADAR_AVATAR_URL` (dashboard) — fill in after the first deploy:
     `https://<presenter host>/avatar`.
3. Deploy. The presenter's first build compiles the Rust service (several minutes); later builds
   reuse the cached layer. It refuses to start if a golden vector fails — check its logs if the
   health check never passes.
4. Point the static site at the presenter: repo *Settings → Secrets and variables → Actions →
   Variables*, add `AVATAR_URL = https://<presenter host>/avatar`, and re-run the pages workflow.
5. Optional: in each Render service, *Settings → Deploy Hook* → copy the URL; add both, separated by
   a space, as the repo **secret** `RENDER_DEPLOY_HOOKS`.

## Costs and limits — read before sharing the link

- **Public sessions (owner decision 2026-10-02).** `FXRADAR_AVATAR_DEV=1` lets any visitor start a
  presenter session without an API key, spending your Anam / ElevenLabs / Anthropic credit. The
  server's monthly caps (300 sessions, 600 minutes, 100k TTS characters) live in a sqlite file that
  a free instance loses when it restarts, so **set spend limits in the three vendor dashboards** —
  they are the real backstop. Anam's dev plan serves one live visitor at a time.
- **Free instances sleep** after 15 minutes without traffic and take about a minute to wake; a paid
  instance stays warm. The Streamlit image is the heavier of the two — if it runs out of memory on
  the free plan, move it to a paid instance.
- **Decision support stays off** (`FXRADAR_AVATAR_ADVICE` unset): offering it to third parties
  likely needs a FinSA review first (docs/AVATAR.md).
- Transcripts are stored server-side as before; on the free plan they vanish with each restart.
