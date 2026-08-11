# Blazecode

Professional lightweight terminal coding agent. Simple, fast, reliable.

## Product

- Stream OpenAI compatible chat, run tools, persist sessions locally
- Tools: read, write, edit, bash, grep, todo
- Approvals: on (confirm every tool) / off (autonomous)
- No MCP, subagents, or IDE integration by design

## Layout

```
blazecode/
  agent/         loop, prompts, tool glue, observer, todos
  llm/           streaming client and model metadata
  tools/         read write edit bash grep todo
  ui/            repl, render, completer
  config/        settings json
  session/       messages and jsonl store
  permissions/   approval gate
  context/       token estimate and compaction
cli.py           typer entry
onboarding.py    first run provider setup
mascot.py        status faces
```

## Rules for changes

- Keep the agent loop UI neutral (no rich or prompt_toolkit in agent/ or llm/)
- Prefer edit over write for existing files
- Do not add dependencies unless required; pin ranges in pyproject.toml
- Comments: short lowercase # notes only when non obvious
- loop.py may grow to ~280 lines; keep other modules focused and small
- Do not break working behavior; run tests before finishing

## Commands

```bash
python -m pip install -e ".[dev]"
python -m pytest -q
python -m blazecode
```

Config and sessions live under `~/.blazecode` (or `$BLAZECODE_HOME`).
User data must never be deleted by install or uninstall scripts.

## Quality bar

- Python 3.11+
- Tests must pass: `python -m pytest -q`
- Paths stay inside cwd; tools go through approval when on
- Secrets: prefer env:VAR keys; never log or print full keys
