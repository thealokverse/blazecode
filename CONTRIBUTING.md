# Contributing to Blazecode

Blazecode is a lightweight terminal coding agent. It streams OpenAI-compatible chat, runs a small set of tools, and keeps configuration local.

Thank you for wanting to help. You do not need to understand the whole project to make a good first change.

## Product philosophy

**Lightweight, fast, reliable, minimal, terminal-native, delightful.**

- Keep the existing header box. Polish what is inside and around it.
- Every visual element should have a purpose. Alive, not noisy.
- No MCP, subagents, or IDE integration. That is a product decision, not a gap.
- Prefer simple, obvious Python over clever abstractions.
- Do not add a dependency unless a change truly needs it.

If a change makes Blazecode feel heavier, slower, or more like another coding agent, it is the wrong change.

## Architecture

```
blazecode/
  agent/         loop, prompts, tool glue, observer, todos
  llm/           streaming client and model metadata
  tools/         read write edit bash grep todo
  ui/            repl, render, completer
  config/        settings json
  session/       messages and jsonl store
  permissions/   approval gate and directory trust
  context/       token estimate, compaction, skills, repo map
cli.py           typer entry
onboarding.py    first-run provider setup
mascot.py        status faces
```

Typical flow: `cli.py` starts a REPL or a one-shot `-p` run. `AgentLoop` streams from the provider, calls tools, and notifies a UI-neutral `Observer`. The REPL implements that observer as `Renderer`.

Keep `agent/` and `llm/` free of `rich` and `prompt_toolkit`. `loop.py` must stay at or under 250 lines.

User data lives in `~/.blazecode` (or `$BLAZECODE_HOME`). Never delete it from install or uninstall scripts.

## Development setup

Python 3.11+ is required.

```bash
python -m pip install -e ".[dev]"
python -m pytest -q
python -m blazecode
```

There is no project linter or type-checker yet. Match the surrounding style:

- 4-space indent
- type hints on new public functions
- short lowercase `# notes` only when the code is not obvious
- prefer `edit` semantics: change existing files instead of adding new ones

## How to structure a change

1. Read `AGENTS.md` and the files you will touch.
2. Keep the change small and aligned with existing patterns.
3. Update callers in the same change. Do not leave shims or deprecated aliases.
4. Add a test only when you introduce a new observable contract, or when a bug is not already covered.
5. Run `python -m pytest -q` before you open a PR.

Good first contributions: a focused bug fix, a missing test for an existing contract, or a small UX polish that does not replace the header box.

## UI/UX principles

- Keep the cyan header `Panel`. Same frame, same identity.
- Prompt stays `blaze (•‿•) ❯`.
- Tool lines stay compact: `  ↳ Read src/main.py`.
- Success and error close with the mascot line.
- Prefer quieter status over extra color, banners, or dashboards.
- Transient live status should be one or two lines and must not redraw the whole terminal.

## Testing

```bash
python -m pytest -q
```

Tests defend behavior: streaming, tools, approvals, trust, skills, compaction, sessions, and the public CLI. Do not assert incidental formatting unless that formatting is the product.

If you change a locked string, update the test in the same commit and say why.

## Commits and pull requests

- One concern per PR.
- Commit messages in the imperative: `Polish /status layout`, not `Polished /status layout`.
- Describe what changed, why, and how you verified it.
- Include `python -m pytest -q` in the PR notes.

## Reporting bugs

Open a GitHub issue with:

- Blazecode version (`blazecode --version`)
- OS and Python version
- Provider and model (no API keys)
- Exact command and what you expected
- A short transcript or screenshot if the bug is visual

Never paste full API keys.

## Proposing features

Open an issue first. Ask whether the feature still fits a small terminal agent.

Strong proposals explain the user problem in one paragraph and a minimal design. Weak proposals add surface area: extra tools, extra modes, extra config, extra UI.

If you are unsure, start a discussion. Small and correct beats large and almost.
