# Hosted static demo

A single self-contained HTML file of the web app that runs with no server. It replays API responses
recorded from a real run of the pipeline on the seeded demo tenant, so it can be shared as a link.
It is read-only: changes return a "read-only demo" message, and Ask answers only the recorded questions.

Re-record and rebuild (API on :8000 with the demo tenant seeded, `npm run dev` available):

```bash
cd frontend
npx playwright test -c demo/playwright.record.config.ts   # crawl every screen, record responses
python3 demo/record_api.py                                # add events, evidence, briefs, Ask answers, comparisons
npm run build:demo                                        # -> dist-demo/xdata-demo.html (+ .artifact.html, body only)
```

Normal builds (`npm run build`) do not include any of this: the demo code is only bundled when `VITE_DEMO=1`.
