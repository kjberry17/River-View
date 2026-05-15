# Taste (Continuously Learned by [CommandCode][cmd])

[cmd]: https://commandcode.ai/

# cli
- Use uv instead of pip for Python package management. Confidence: 0.65

# communication
- When user says "explain only", provide explanation without executing commands or making changes. Confidence: 0.75

# web-search
- Use DuckDuckGo (ddgs/duckduckgo_search library) for web search in the AI Buddy, not TinyFish. Confidence: 0.70

# export
- Export downloadable reports as Markdown files. Confidence: 0.65

# formatting
- Use tables, bullets, and rich typography for client-facing report output. Confidence: 0.65

# streaming-ui
- Use a persistent working indicator (not removed on first tool event) that stays visible throughout streaming agent processing between tool calls. Confidence: 0.70

# workflow
- Commit current changes as a git restore point before implementing major feature changes. Confidence: 0.65

