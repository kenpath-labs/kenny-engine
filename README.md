# Kenny Engine

The AI engine behind [Kenny Review](https://github.com/kenpath-labs/kenny-review) —
kenpath-labs' self-hosted PR review bot. A fork of the MIT-licensed
[PR-Agent](https://github.com/The-PR-Agent/pr-agent) with:

- **`/kenny/v1` JSON API** (`pr_agent/servers/kenny_api.py`) — run `describe`
  (the explainer), `review`, `ask`, and line-level explanations in-process and get
  structured JSON back instead of PR comments. Auth via `X-Kenny-Key`.
- **Provider store** (`pr_agent/kenny/provider_store.py`) — model/endpoint config
  lives in Postgres, managed from the Kenny Review dashboard. Keys are
  Fernet-encrypted; the engine is the only decryptor. Webhook auto-reviews use the
  active provider automatically.
- **Kenny branding** on everything it posts to GitHub.
- Upstream fixes (marked `# KENNY`): `pr_questions` / `pr_line_questions` honor
  `publish_output=false` and expose their answer as an artifact.

## Run

```bash
gunicorn -k uvicorn.workers.UvicornWorker --timeout 300 -w 2 pr_agent.servers.kenny_server:app
```

One app serves both the GitHub webhook (`/api/v1/github_webhooks`) and the Kenny
JSON API (`/kenny/v1/*`).

Env: `KENNY_API_KEY`, `DATABASE_URL`, `KENNY_SECRET_KEY`,
`GITHUB__DEPLOYMENT_TYPE=user`, `GITHUB__USER_TOKEN`, `GITHUB__WEBHOOK_SECRET`,
plus bootstrap model config (`CONFIG__MODEL`, `OPENAI__API_BASE`, `OPENAI__KEY`)
used until a provider is configured in the dashboard.

## Upstream

Sync with `git fetch upstream && git merge upstream/main`. Keep Kenny changes in
`pr_agent/kenny/`, `pr_agent/servers/kenny_*.py`, or marked `# KENNY`.

Licensed MIT, © the PR-Agent contributors and Kenpath Labs. This fork is not
affiliated with Qodo.
