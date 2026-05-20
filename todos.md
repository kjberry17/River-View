# Project Todos

## In Progress
- [ ] None

## Completed
- [x] Switch AI backend from OpenRouter (free, flaky models) → OpenAI (gpt-4o-mini primary, gpt-4o fallback)
- [x] Fix "response was empty" error caused by unreliable free models
- [x] Remove "free AI models" language from frontend error messages
- [x] Update all model name references (DeepSeek → GPT-4o Mini) in ai_buddy.py, app.py, index.html
- [x] Configure and start Oregon Fishing Dashboard workflow

## Backlog
- [ ] Add model selector UI in The Fisher chat tab (let user switch between gpt-4o-mini and gpt-4o)
- [ ] Validate OPENAI_API_KEY on startup and surface a clear error in the UI if missing/invalid
- [ ] Add retry button to The Fisher chat when a response fails
