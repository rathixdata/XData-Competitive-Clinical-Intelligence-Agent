# Run XData CI Agent on your Mac (one command, nothing to install first)

1. Open **Terminal**: press Cmd+Space, type `Terminal`, press Return.
2. Paste this line and press Return:

   ```bash
   curl -fsSL https://raw.githubusercontent.com/rathixdata/XData-Competitive-Clinical-Intelligence-Agent/refs/heads/claude/laughing-knuth-16lb2c/desktop/install-mac.sh | bash
   ```

3. Type the email address you want to sign in with when it asks, and press Return.
4. Wait about 5 minutes. Your browser opens the app, and the Terminal window shows your sign-in details
   (organisation workspace `my-company`, your email, and a generated password). They are also saved in
   `~/XData-CI-Agent/LOGIN.txt`.

Keep the Terminal window open while you use the app. Close it (or press Ctrl-C) to stop the app.
Next time, double-click **Start XData CI Agent** on your Desktop.

## What it is

The complete system running on your computer, with live data: ClinicalTrials.gov, PubMed and FDA monitoring,
change detection, importance scoring against your drugs, evidence-checked summaries, Ask, alerts and briefs.
It does not need Docker, Homebrew, Xcode, Python, Node or an administrator password. Everything is kept in
`~/XData-CI-Agent`: a private Python, an embedded PostgreSQL 16 with pgvector, the app, and your data.

- **Your data stays on your Mac** in `~/XData-CI-Agent/data`. Running the install command again updates the app
  and keeps your data.
- **AI-written summaries and answers (optional):** add `XDATA_ANTHROPIC_API_KEY=sk-ant-...` to
  `~/XData-CI-Agent/settings.env` (get a key at https://console.anthropic.com), then restart the app. Without a
  key, summaries contain only verified facts from the sources.
- **Monitoring runs while the app is open.** Sources are checked several times a day; use
  Competitor landscape > Setup & thresholds > "Check sources now" to check immediately.
- **Uninstall:** quit the app, then delete the `~/XData-CI-Agent` folder and the Desktop icon.

## If something goes wrong

The installer stops with a red message and asks for a screenshot. Logs from the web build are in
`~/XData-CI-Agent/npm-install.log` and `~/XData-CI-Agent/web-build.log`.
