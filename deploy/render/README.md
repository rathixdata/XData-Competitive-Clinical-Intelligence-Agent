# Deploy to Render (one click, runs in your browser)

[![Deploy to Render](https://render.com/images/deploy-to-render-button.svg)](https://render.com/deploy?repo=https://github.com/rathixdata/XData-Competitive-Clinical-Intelligence-Agent)

This runs the complete system, not a demo: live ClinicalTrials.gov, PubMed and openFDA monitoring, change
detection, importance scoring, impact mapping, evidence-checked AI summaries, Ask, alerts and briefs.

## Steps

1. Click the button above and sign in to Render (a free account is fine; you can sign up with GitHub).
2. Render shows the Blueprint with two resources: **xdata-ci-agent** (the app) and **xdata-db** (the database).
   Fill in:
   - `XDATA_BOOTSTRAP_TENANT_NAME`: your company name, e.g. `Acme Bio`.
   - `XDATA_BOOTSTRAP_ADMIN_EMAIL`: the email you will sign in with.
   - `XDATA_BOOTSTRAP_ADMIN_PASSWORD`: at least 12 characters. Keep it safe.
   - `XDATA_ANTHROPIC_API_KEY` (optional): a Claude API key from https://console.anthropic.com for AI-written
     summaries and answers. Without it the app writes evidence-only summaries from the source data.
   - `XDATA_NCBI_EMAIL` and `XDATA_SEC_USER_AGENT` (optional): leave empty to use your admin email.
3. Click **Apply**. The first build takes about 5-10 minutes.
4. Open the URL Render shows (like `https://xdata-ci-agent-xxxx.onrender.com`) and sign in with:
   - Organisation workspace: `my-company`
   - Email and password: the ones you entered in step 2.

Within a few minutes of the first start the app pulls live records. Recently registered NSCLC trials and new
publications appear as the first changes; later runs report what changed in each source since the last run.

## Make it yours

- Open your drug (the starter is `XD-101`, a placeholder NSCLC profile) and edit its profile: target,
  mechanism, indication, line of therapy, biomarker, endpoint. Impact mapping and scores use this profile.
- Change the searches of the starter competitor landscape, or create more landscapes, to match your portfolio.
- Invite colleagues from Settings > Users.

## Good to know

- **Free plan limits.** The free web service sleeps after 15 minutes without visitors and wakes on the next
  visit (about a minute). While it sleeps no monitoring runs. For continuous monitoring and timely alerts,
  switch the service to the **Starter** plan in Render. The free database expires after 30 days unless you
  upgrade it; upgrade before then to keep your data.
- **What runs where.** One container serves the web app and the API and runs the source schedule, change
  processing and alert delivery in a background thread (`XDATA_INPROCESS_SCHEDULER`). Raw source documents are
  kept write-once in Postgres (`XDATA_OBJECT_STORE_BACKEND=postgres`) because free instances have no durable
  disk. For larger installations use the multi-service setup in `deploy/k8s` or `deploy/terraform` (separate
  workers, Redis, S3 with Object Lock).
- **Email, Slack or Teams alerts.** Add `XDATA_SMTP_HOST`, `XDATA_SMTP_USERNAME`, `XDATA_SMTP_PASSWORD` and
  `XDATA_SMTP_FROM` in the service's Environment tab for email. Slack, Teams and webhook destinations are set per
  alert rule in the app.
- **Logs.** If the service does not start, open it in Render and check **Logs**. The startup steps are
  printed as `==> Waiting for the database`, `==> Applying database migrations`, `==> Creating the first workspace`.
  A missing admin email or a password shorter than 12 characters stops the first start with a clear message;
  fix it under **Environment** and redeploy.
