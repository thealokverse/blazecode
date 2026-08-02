# Blazecode

**A lightweight terminal coding agent.**

Blazecode streams responses from OpenAI-compatible APIs, edits your project with a small set of tools, and keeps configuration local. 

```text
blaze (•‿•) ❯
```

<p align="center">
  <img src="./assets/blazecode.png" alt="Blazecode demo" width="85%" />
</p>

---

## Install

**One-liner** (Linux & macOS):

```bash
curl -fsSL https://raw.githubusercontent.com/thealokverse/blazecode/main/install.sh | bash
```

This creates an isolated venv in `~/.local/share/blazecode` and links `blazecode` to `~/.local/bin`.  
Your config and sessions in `~/.blazecode` are never touched.

| Action | Command |
|--------|---------|
| Update | `curl -fsSL https://raw.githubusercontent.com/thealokverse/blazecode/main/install.sh \| bash` |
| Uninstall | `curl -fsSL https://raw.githubusercontent.com/thealokverse/blazecode/main/install.sh \| bash -s -- --uninstall` |
| Pin version | `curl -fsSL ... \| bash -s -- --version v1.2.0` |

Requirements: **Python 3.11+**, `curl` (or `wget`), `tar`.

### Other install methods

```bash
# pip (from GitHub)
pip install git+https://github.com/thealokverse/blazecode.git

# uv
uv tool install git+https://github.com/thealokverse/blazecode.git
```

---

## Quick start

```bash
blazecode                          # interactive REPL (onboarding on first run)
blazecode -p "Explain this repo"   # one-shot prompt
blazecode --version
```

First launch walks you through a provider (OpenAI, Google, OpenRouter, Groq, Z.ai, Kimi, Ollama, or custom) and writes `~/.blazecode/config.json`.

---

## Features

- **Streaming** responses with a live status mascot
- **Five tools**: `read`, `write`, `edit`, `bash`, `grep`
- **Providers**: OpenAI-compatible endpoints with curated text/code model selection
- **Reasoning modes**: `none`, `low`, `medium`, `high`, `xhigh`, `max`, or per-turn `adaptive`
- **Approvals**: `/approval on|off` for shell command confirmation
- **Sessions**: append-only JSONL under `~/.blazecode/sessions`
- **Skills**: optional Markdown instructions, loaded when relevant
- **Compaction**: keeps context lean on long chats

---

## Configuration

```json
{
  "default_provider": "openai",
  "default_model": "gpt-4.1",
  "approval_mode": "on",
  "reasoning_effort": "none",
  "providers": [
    {
      "name": "openai",
      "base_url": "https://api.openai.com/v1",
      "api_key": "env:OPENAI_API_KEY",
      "models": ["gpt-4.1", "gpt-4.1-mini"]
    },
    {
      "name": "ollama",
      "base_url": "http://localhost:11434/v1",
      "api_key": "none",
      "models": ["qwen2.5-coder:7b"]
    }
  ]
}
```

Prefer `env:VARIABLE` for API keys. Inline keys are stored with `0600` permissions and never printed in full.

| `approval_mode` | Behavior |
|-----------------|----------|
| `on` | Confirm before shell (`bash`) commands |
| `off` | Run all tools without prompts |

`reasoning_effort` accepts `none`, `low`, `medium`, `high`, `xhigh`, `max`, or `adaptive`. Adaptive asks the active model to select one concrete effort once per user turn and reuses it throughout that turn's tool loop. Unsupported effort levels are rejected by the selected provider.

---

## Terminal commands

Type `/` for fuzzy completion.

| Command | Purpose |
|---------|---------|
| `/status` | Provider, model, reasoning, approval, tokens, mascot |
| `/approval on\|off` | Confirm shell commands, or run tools freely |
| `/reasoning <mode>` | Set or inspect reasoning effort |
| `/provider` | Add or switch provider |
| `/models` | Switch models |
| `/skills` | List skills; `/skills add <file.md or directory>` installs one |
| `/export` | Export session to Markdown |
| `/clear` | Start a fresh session |
| `/resume` | Resume a saved session |
| `/exit` | Quit |

---

## Tools & skills

| Tool | Role |
|------|------|
| `read` | Read a file (offset/limit) |
| `write` | Create or replace a file |
| `edit` | Exact string replacement |
| `bash` | Foreground shell command (timeout) |
| `grep` | Regex search |

Paths stay inside the working directory. Shell commands go through the approval gate when approval is on.

**Skills** are Markdown instructions in `~/.blazecode/skills/` or `./.blazecode/skills/`. Drop in a file such as `review.md`, or keep using a legacy directory containing `SKILL.md`. Blazecode ships with a Planner example skill. Only names/descriptions enter the base prompt; full instructions load when the task matches.

Project guidance is loaded from `AGENTS.md` in the working directory when present.


---

## Development

```bash
python -m pip install -e ".[dev]"
python -m pytest -q
python -m blazecode
```

---

## Uninstall notes

`install.sh --uninstall` removes only the program (`~/.local/share/blazecode` and the `blazecode` link).  
It **does not** delete `~/.blazecode`. To wipe user data:

```bash
rm -rf ~/.blazecode
```

---

## License

[MIT](./LICENSE)
