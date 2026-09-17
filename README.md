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
- **Jev-first cascade** (`pr_agent/kenny/jev_*.py`) — TypeSafe System One (Jev)
  runs structured sanity checks before the LLM review; high-confidence findings
  can auto-comment, mid-confidence hints feed the LLM.
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

### TypeSafe / Jev install

```bash
pip install -r requirements.txt
# If typesafe-sdk is not on public PyPI yet:
pip install 'typesafe-sdk>=0.5.7' --extra-index-url https://pypi.typesafe.ai/
```

## Jev-first cascade (TypeSafe System One)

Kenny can triage diffs with [Jev](https://typesafe.ai) before the generative LLM
review. Jev is non-generative: you send structured **state** + typed questions
(**Noul** / **Score**); it returns probabilities your code routes on.

### Behaviour

| Mode | When | What happens |
|------|------|----------------|
| **Commit checks** | `POST /kenny/v1/jev-check` with `commit_url` or `owner`+`repo`+`commit_sha` | Jev-only sanity on the commit's file patches. High-confidence findings can be posted as a **commit comment** when `publish=true`. |
| **PR cascade** | `POST /kenny/v1/review` (default) | 1) Jev runs on the PR diff 2) `auto_comment` findings publish immediately (marker `<!-- kenny-jev -->`) 3) `hint_for_llm` findings are injected into `pr_reviewer.extra_instructions` 4) LLM `/kenny/v1/review` still owns explain/improve prose. Pass `skip_jev=true` to disable for one call. |
| **PR Jev-only** | `POST /kenny/v1/jev-check` with `pr_url` | Same checks as the cascade pre-step; optional publish. |

Rules checked (parallel Noul + Score per file): `secrets_or_credentials`,
`dangerous_destructive_ops`, `auth_or_payments_touch`,
`missing_tests_for_api_surface`, `pii_exposure`.

### Env vars

| Variable | Default | Meaning |
|----------|---------|---------|
| `TYPESAFE_API_KEY` | _(unset)_ | TypeSafe API key. Required for Jev. |
| `TYPESAFE_MODEL` | `jev-latest` | System One model id. |
| `JEV_ENABLED` | `true` if `TYPESAFE_API_KEY` set, else false | Master switch. |
| `JEV_COMMIT_CHECKS` | `true` | Allow commit-sha path on `/jev-check`. |
| `JEV_PR_CASCADE` | `true` | Run Jev before `/review`. |
| `JEV_AUTO_COMMENT_MIN` | `0.85` | Noul P(yes) ≥ this → `auto_comment`. |
| `JEV_HINT_MIN` | `0.55` | Noul P(yes) ≥ this → `hint_for_llm`. |

### Commit-diff note

PR diffs use the existing git-provider `get_diff_files()` helpers. The commit path
uses GitHub's Commits API (`repo.get_commit(sha).files[].patch`) via PyGithub /
`GithubProvider`. It does **not** run a full `compare` against an arbitrary base;
for multi-commit PR context prefer `pr_url`.

### Example

```bash
curl -s -X POST "$ENGINE/kenny/v1/jev-check" \
  -H "X-Kenny-Key: $KENNY_API_KEY" \
  -H "Content-Type: application/json" \
  -d '{"pr_url":"https://github.com/org/repo/pull/1","publish":false}'
```

## Upstream

Sync with `git fetch upstream && git merge upstream/main`. Keep Kenny changes in
`pr_agent/kenny/`, `pr_agent/servers/kenny_*.py`, or marked `# KENNY`.

Licensed MIT, © the PR-Agent contributors and Kenpath Labs. This fork is not
affiliated with Qodo.
