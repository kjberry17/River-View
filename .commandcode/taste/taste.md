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

# mobile-design
- Use mobile-first design approach; fix horizontal scrolling and ensure responsive layouts for all pages. Confidence: 0.75

# ai-model
- Use DeepSeek V4 Flash as the only AI model; remove dropdown model choices. Confidence: 0.80

# workflow
- Commit current changes as a git restore point before implementing major feature changes. Confidence: 0.65
- When debugging AI/streaming agent issues, reproduce the problem with real test queries before diving into code analysis. Confidence: 0.60
- When user requests a specific output file (e.g., handoff.html), stop current investigation and produce that file immediately rather than continuing analysis. Confidence: 0.75

