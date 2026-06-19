# BlazeCode 🔥

**A lightweight, blazing-fast, terminal-based AI coding agent.**

BlazeCode combines the simplicity of Codex CLI's chat-style interface with multi-provider flexibility — no full-screen TUI, no client/server, just a single scrolling conversation that feels like pairing with a sharp colleague.

---

## Installation 🚀

Install directly from GitHub (no PyPI needed):

```bash
pip install git+https://github.com/thealokverse/blazecode.git
```

> **Requirements:** Python 3.11+

---

## Quick Start

Run it:

```bash
blazecode
```

On first launch, the **interactive Onboarding Wizard** walks you through:

1. **Choosing a provider** — OpenAI, Anthropic, Gemini, OpenRouter, or Ollama
2. **Entering your API key** (saved securely to `~/.blazecode/auth.json`, chmod 600)
3. **Selecting a model** — dynamically fetched from your provider's API

After setup, you're dropped straight into a chat session. Type your request; BlazeCode reads, writes, edits files, runs shell commands, and streams the answer back.

For a single non-interactive turn (scripting / CI):

```bash
blazecode "fix the off-by-one error in main.py"
```

---

## Features ✨

| | |
|---|---|
| **Codex CLI-style UI** | Thick shaded prompt bar (`bg:#2a2b36`) with a live mascot face that reflects what BlazeCode is doing — thinking `(•̀ᴗ•́)`, searching `(⌕‿⌕)`, editing `(⌐■_■)`, debugging `(ಠ_ಠ)` |
| **Multi-provider** | OpenAI, Anthropic, Gemini, OpenRouter, Ollama — all through a unified interface. No high-level wrappers (no litellm), just native SDKs |
| **Native OpenAI-compatible** | Uses `AsyncOpenAI` directly for OpenAI, Gemini (Google OpenAI-compatible endpoint), OpenRouter, and Ollama; `AsyncAnthropic` for Anthropic |
| **Dynamic model fetching** | Lists available models from your provider at setup and on demand via `/models` |
| **Exact string-matching editor** | The `edit` tool replaces the *first exact match* of a given string — no regex, no ambiguity, no accidental corruption |
| **Agentic tool loop** | Read, write, edit, glob, grep, shell — with automatic iteration until the task is complete (up to 25 rounds by default) |
| **Approval workflow** | File writes and shell commands require confirmation by default. Toggle with `--permission auto`, `/yolo`, or `/permission` |
| **Session persistence** | Every conversation is saved as JSONL to `./sessions/`. Resume with `blazecode -r <session_id>` |
| **Slash commands** | Full set of in-chat controls (see below) |
| **Markdown rendering** | All output renders with syntax-highlighted code blocks and clean formatting |

---

## Supported Providers

| Provider | Model prefix | Env var | Notes |
|---|---|---|---|
| **OpenAI** | `gpt-4o` / `gpt-5` | `OPENAI_API_KEY` | Native `AsyncOpenAI` |
| **Anthropic** | `claude-sonnet-4-6` / `claude-3-7-sonnet` | `ANTHROPIC_API_KEY` | Native `AsyncAnthropic` |
| **Gemini** | `gemini-2.5-pro` | `GEMINI_API_KEY` | Google OpenAI-compatible endpoint |
| **OpenRouter** | `openrouter/*` | `OPENROUTER_API_KEY` | Pass-through to 200+ models |
| **Ollama** | `llama3` / `mistral` / `codellama` | *(none)* | Local, `http://localhost:11434` |

API keys can also be stored in `~/.blazecode/auth.json` (set during onboarding).

---

## Slash Commands

| Command | Action |
|---|---|
| `/help` | Show available commands |
| `/status` | Display current model, provider, permission mode, token count |
| `/provider` | Show current provider and list available providers |
| `/model` or `/models` | Fetch available models from the current provider and switch |
| `/permission` | Toggle between `ask` (confirm each tool) and `auto` (auto-approve) |
| `/yolo` | Enable auto-approve for the rest of the session |
| `/clear` | Clear the terminal screen |
| `/export` | Export the session to `.blazecode/exports/<session-id>.md` |
| `/skills` | Append a persistent skill to `~/.blazecode/skills.md` |
| `/resume` | Show the current session ID (for `blazecode -r`) |
| `/exit` | Quit BlazeCode |

---

## Configuration

| File | Purpose |
|---|---|
| `~/.blazecode/config.toml` | Default provider and model |
| `~/.blazecode/auth.json` | API keys (auto-created by the wizard, **chmod 600**) |
| `~/.blazecode/skills.md` | Persistent skills injected into every session's system prompt |

---

## Examples

```bash
# Start an interactive session
blazecode

# Run a single task and exit
blazecode "add error handling to src/api.py"

# Resume a previous session
blazecode -r 20260619-135009-feeccd

# Skip approval prompts
blazecode --permission auto
```

---

## Project Structure

```
blazecode/
├── pyproject.toml
├── README.md
├── LICENSE
└── src/
    └── blazecode/
        ├── __init__.py
        ├── __main__.py          # python -m blazecode support
        ├── cli/app.py           # Entry point, interactive & non-interactive loops
        ├── core/
        │   ├── config.py        # Config loading, auth, onboarding wizard
        │   ├── errors.py        # ModelNotFoundError
        │   ├── events.py        # MascotState, TextDelta, ToolCallRequested, etc.
        │   └── permissions.py   # PermissionPolicy (ask / auto)
        ├── engine/
        │   ├── loop.py          # Agent class, run_turn, tool execution loop
        │   └── session.py       # Session, SessionPaths, JSONL persistence
        ├── providers/
        │   ├── client.py        # ProviderClient with _stream_openai / _stream_anthropic
        │   └── registry.py      # PROVIDERS dict, system prompt, display_model
        ├── tools/
        │   ├── base.py          # Tool abstract base class
        │   ├── read.py          # Read files with line-range support
        │   ├── write.py         # Write files (creates parent dirs)
        │   ├── edit.py          # Exact-string replacement editor
        │   ├── glob_tool.py     # Glob with .gitignore respect
        │   ├── grep.py          # Regex search across files
        │   ├── shell.py         # Shell command execution (120s default timeout)
        │   └── registry.py      # ToolRegistry
        └── ui/
            └── terminal.py      # Codex-style prompt bar, markdown rendering, mascot faces
```

---

## License

MIT © BlazeCode Authors
