# Oregon OSINT Dashboard

This repository currently defaults to the Oregon fishing Flask dashboard in
`artifacts/fishing-dashboard`.

## Run On Replit

Import the GitHub repository into Replit. The `.replit` file sets
`artifacts/fishing-dashboard/app.py` as the entrypoint and the Run button
installs dependencies from `artifacts/fishing-dashboard/requirements.txt`
before starting `artifacts/fishing-dashboard/start.sh` on port `5000`.

Set secrets in Replit Secrets rather than committing an `.env` file:

- `OPENROUTER_API_KEY`: required for AI chat.
- `OPENAI_API_KEY`: optional fallback for AI chat when OpenRouter models fail.
- `OPENAI_FALLBACK_MODEL`: optional OpenAI fallback model override. Defaults to
  `gpt-4o-mini`.
- `DATABASE_URL`: optional for boot, recommended for wiki entries,
  preferences, fishing logs, and chat tools that use persistence.
- `AIRNOW_API_KEY`: optional for live AQI data. AQI routes fall back to
  estimated guidance without it.

Rotate any real API keys that were committed before pushing this repo to
GitHub.

## Local Development

From the repo root:

```bash
python -m pip install -r artifacts/fishing-dashboard/requirements.txt
PORT=5000 bash artifacts/fishing-dashboard/start.sh
```

Health check:

```bash
curl http://localhost:5000/_stcore/health
```

The current git remote may be named `gitsafe-backup`. Add or rename a real
GitHub `origin` before importing the project into Replit from GitHub.
