# Deploy on Google Cloud Run (managed containers, no VM to look after)

Cloud Run runs the same image as the Oracle path (`deploy/Dockerfile`), gives you an HTTPS URL
immediately, scales to zero or stays warm, and needs no server maintenance. Trade-off vs Oracle:
it is not free if you keep it always-on.

**Cost (europe-west1, 1 vCPU / 2 GiB, CPU billed only while serving):**
- `min-instances=1` (always warm, no cold start): ≈ **$8–10 / month** idle charge + a few cents of use.
- `min-instances=0`: usually **$0** inside the free tier, but the first visitor after idle waits **5–10 s**
  (container start + Python imports). Still far better than Streamlit Cloud's sleep screen.

The daily pipeline runs in GitHub Actions and commits artifacts to `main`; the `cloud run` workflow
rebuilds the image (artifacts are baked in) and redeploys after every refresh, so the service is
always current. Nothing is computed on Cloud Run (rule 8).

## 0. Prerequisites (10 minutes, once)

Install the CLI: https://cloud.google.com/sdk/docs/install, then:

```bash
gcloud auth login
export PROJECT=fx-regime-radar-$RANDOM   # any unique id
export REGION=europe-west1
gcloud projects create $PROJECT && gcloud config set project $PROJECT
# link billing in the console (Billing → link account) — required even for free-tier usage
gcloud services enable run.googleapis.com artifactregistry.googleapis.com cloudbuild.googleapis.com secretmanager.googleapis.com
gcloud artifacts repositories create fxradar --repository-format=docker --location=$REGION
```

## 1. Manual deploy (no local Docker needed — Cloud Build builds the image)

```bash
cd fx-regime-radar
gcloud builds submit --config deploy/cloudbuild.yaml --substitutions _REGION=$REGION,_REPO=fxradar .
gcloud run deploy fx-regime-radar \
  --region $REGION --platform managed \
  --image $REGION-docker.pkg.dev/$PROJECT/fxradar/app:latest \
  --port 8080 --allow-unauthenticated \
  --cpu 1 --memory 2Gi --concurrency 40 --timeout 3600 --session-affinity \
  --min-instances 1 --max-instances 3
```

The command prints the service URL (`https://fx-regime-radar-….a.run.app`). Flags that matter for
Streamlit: `--timeout 3600` (its websocket is one long request; the client reconnects after),
`--session-affinity` (reconnects hit the same instance), `--port 8080` (the image reads `$PORT`).
Use `--min-instances 0` for the free-tier variant.

## 2. Automatic redeploys from GitHub (recommended)

Create a deploy service account and give GitHub its key:

```bash
gcloud iam service-accounts create gh-deploy --display-name "GitHub Actions deploy"
SA=gh-deploy@$PROJECT.iam.gserviceaccount.com
for role in roles/run.admin roles/artifactregistry.writer roles/iam.serviceAccountUser; do
  gcloud projects add-iam-policy-binding $PROJECT --member serviceAccount:$SA --role $role --quiet
done
gcloud iam service-accounts keys create gh-deploy.json --iam-account $SA
```

In the GitHub repo → *Settings → Secrets and variables → Actions*:
- **Secret** `GCP_SA_KEY` = the contents of `gh-deploy.json` (then delete the local file).
- **Variables** `GCP_PROJECT` = your project id; optional `GCP_REGION` (default `europe-west1`),
  `CLOUDRUN_SERVICE` (default `fx-regime-radar`), `CLOUDRUN_MIN_INSTANCES` (`1` always-on, `0` free).

That's it: `.github/workflows/cloudrun.yml` is inactive until `GCP_PROJECT` exists, then it builds and
deploys on every push touching the app/artifacts and after every successful `daily-refresh` run
(that commit carries `[skip ci]`, so the workflow listens to the run instead of the push). Trigger it
by hand once from *Actions → cloud run → Run workflow*.

Optional LLM key without putting it in the image: `gcloud secrets create anthropic-api-key --data-file=-`
(paste the key, Ctrl-D), grant the *Cloud Run runtime* service account `roles/secretmanager.secretAccessor`,
and set the repo variable `ANTHROPIC_SECRET_NAME=anthropic-api-key`. Without it the app uses the template.

## 3. Custom domain (optional)

*Cloud Run → service → Integrations / Manage custom domains* (or `gcloud beta run domain-mappings create`),
add the CNAME it shows at your DNS provider; certificates are automatic.

## Notes and limits

- The container filesystem is in-memory and per instance: the arcade's local sqlite (`data/arcade.db`)
  works but resets on new instances — fine for a demo, and the reason for `--session-affinity`.
- Cold start with `min-instances=0` is dominated by Python imports (pandas, sklearn, hmmlearn); the image
  itself is cached by Cloud Run.
- Compare: Oracle Always-Free ([DEPLOY_ORACLE.md](DEPLOY_ORACLE.md)) is €0 and always-on but you own a VM;
  Cloud Run is zero-ops but ≈ $8–10/month to keep warm.
