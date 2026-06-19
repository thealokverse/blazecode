# BlazeCode

BlazeCode is a lightweight, fast, terminal-based AI coding agent written in Python. It combines the simplicity of codex CLI's chat-style interface with the multi-provider flexibility of aider, in a single scrolling conversation with Blaze — your coding mascot.

## Features

- Single scrolling terminal conversation — no full-screen TUI, no client/server
- Multiple LLM providers: OpenAI, Anthropic, Gemini, Groq, Ollama, OpenRouter, and any OpenAI-compatible endpoint
- Six tools: `read`, `write`, `edit` (exact search/replace), `glob`, `grep`, `shell`
- First-time **onboarding wizard** picks your provider, asks for an API key, and selects a model
- **Blaze mascot** with stateful faces: idle, thinking, searching, editing, debugging, success, error
- Codex-style header: `>_ BlazeCode (v1.0.0)` + provider/model/directory/mode
- Slash autocomplete via `prompt_toolkit.WordCompleter`
- Slash commands: `/help`, `/status`, `/provider`, `/models`, `/skills`, `/export`, `/clear`, `/resume`, `/yolo`, `/exit`
- **Skills**: drop project rules into `~/.blazecode/skills.md` and `/skills` injects them into the system prompt
- Persistent sessions as JSONL in `~/.blazecode/sessions/`
- Markdown rendering with syntax-highlighted code blocks and unified diffs for approvals

## Install

```bash
cd blazecode
pip install -e .
```

## Usage

```bash
blazecode              # start the interactive chat (onboarding on first run)
blazecode --help       # show help
blazecode --version    # show version
```

That's the entire CLI. Everything else lives inside the chat as slash commands.

## Slash commands

| Command         | Action                                          |
| --------------- | ----------------------------------------------- |
| `/help`         | Show available commands                         |
| `/status`       | Re-print the Codex-style header                 |
| `/provider`     | Switch provider (re-prompts for API key)        |
| `/models`       | List and switch models for the current provider |
| `/skills`       | Load `~/.blazecode/skills.md` into the system prompt |
| `/export <path>` | Export the session as Markdown                  |
| `/clear`        | Clear the visible screen                        |
| `/resume`       | Pick and resume a saved session                 |
| `/yolo`         | Toggle auto-approve for this session            |
| `/exit`         | Quit BlazeCode                                  |

Slash autocomplete is wired up — type `/` and you'll see the menu.

## Mascot states

| Face | State | When |
| --- | --- | --- |
| `(•‿•)` | Idle | Waiting for user input |
| `(•̀ᴗ•́)` | Thinking | Waiting on the LLM |
| `(⌕‿⌕)` | Searching | Running `read`, `glob`, `grep` |
| `(⌐■_■)` | Editing | Running `write` or `edit` |
| `(ಠ_ಠ)` | Debugging | Running `shell` or handling an error |
| `(ᵔ◡ᵔ)` | Success | Turn completed cleanly |
| `(╥﹏╥)` | Error | Turn failed |

## Configuration

Config lives at `~/.blazecode/config.toml`:

```toml
[default]
model = "claude"
permission = "ask"
max_iterations = 25

[providers.anthropic]
api_key = "sk-ant-..."
```

API keys in TOML only set the environment variable if it isn't already set in the real environment — real env vars always win.

## Skills

Write Markdown rules in `~/.blazecode/skills.md`:

```markdown
# Skills

- Always run tests after editing Python files.
- Prefer `pathlib.Path` over `os.path` joins.
```

Run `/skills` in any session to inject those rules into the system prompt. The file is auto-created with a starter template on first use.

## Repository layout

```
blazecode/
├── pyproject.toml
├── README.md
├── LICENSE
├── src/
│   └── blazecode/
│       ├── __init__.py
│       ├── __main__.py
│       ├── cli/
│       │   └── app.py             # argparse + onboarding wizard + dispatch
│       ├── core/
│       │   ├── config.py          # load/save ~/.blazecode/config.toml
│       │   ├── errors.py          # custom exception hierarchy
│       │   ├── events.py          # pydantic event models
│       │   └── permissions.py     # ask / auto / deny-shell modes
│       ├── engine/
│       │   ├── loop.py            # agent run loop, retries, tool dispatch
│       │   └── session.py         # history, JSONL persistence, truncation
│       ├── providers/
│       │   ├── client.py          # AsyncOpenAI streaming wrapper
│       │   └── registry.py        # provider / model shortcuts
│       ├── tools/
│       │   ├── base.py
│       │   ├── read.py
│       │   ├── write.py
│       │   ├── edit.py
│       │   ├── glob_tool.py
│       │   ├── grep.py
│       │   ├── shell.py
│       │   └── registry.py        # tool dispatch + mascot mapping
│       └── ui/
│           └── terminal.py        # Codex-style REPL, mascot, slash commands
└── tests/
```

## License

MIT.
