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

### Linux & macOS

```bash
curl -fsSL https://raw.githubusercontent.com/thealokverse/blazecode/main/install.sh | bash
```

This creates an isolated venv in `~/.local/share/blazecode` and links `blazecode` to `~/.local/bin`.  
Your config and sessions in `~/.blazecode` are never touched.

| Action | Command |
|--------|---------|
| Update | `curl -fsSL https://raw.githubusercontent.com/thealokverse/blazecode/main/install.sh \| bash` |
| Uninstall | `curl -fsSL https://raw.githubusercontent.com/thealokverse/blazecode/main/install.sh \| bash -s -- --uninstall` |
| Pin version | `curl -fsSL ... \| bash -s -- --version v1.2.1` |

Requirements: **Python 3.11+**, `curl` (or `wget`), `tar`.

### Windows

In **PowerShell** (5.1+ or PowerShell 7):

```powershell
irm https://raw.githubusercontent.com/thealokverse/blazecode/main/install.ps1 | iex
```

This creates an isolated venv in `%LOCALAPPDATA%\blazecode` and places a `blazecode.cmd` shim
in `%LOCALAPPDATA%\blazecode\bin`, which is added to your **user PATH**.  
Your config and sessions in `~/.blazecode` are never touched.

| Action | Command |
|--------|---------|
| Update | re-run the `irm ... \| iex` line above |
| Uninstall (local file) | `.\install.ps1 -Uninstall` |
| Uninstall (piped) | `$env:BLAZECODE_UNINSTALL = '1'; irm https://raw.githubusercontent.com/thealokverse/blazecode/main/install.ps1 \| iex` |
| Pin version | `.\install.ps1 -Version 1.2.1` |

Requirements: **Windows 10+**, **Python 3.11+** (`winget install Python.Python.3.12` or from [python.org](https://www.python.org/)). The installer prefers the `py` launcher, then falls back to `python`/`python3`.

> **PATH note:** the shim dir is added to your *user* PATH (no admin rights needed). Open a **new** terminal after install for `blazecode` to be found.

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
blazecode --resume                 # resume the most recent session directly
blazecode -p "Explain this repo"   # one-shot prompt
blazecode --version
```

First launch walks you through a provider (OpenAI, Anthropic, Google, OpenRouter, Groq, Z.ai, Kimi, DeepSeek, MiniMax, Ollama, or custom) and writes `~/.blazecode/config.json`.

---

## Features

- **Streaming** responses with live markdown, syntax-highlighted code, and diffs
- **Multiline input**: enter to send, shift+enter for a new line
- **Tools**: `read`, `write`, `edit`, `bash`, `grep`, `todo` (bash streams live output)
- **Providers**: OpenAI-compatible endpoints with curated text/code model selection
- **Approvals**: `/approval on` to confirm every tool; `/approval off` for autonomous runs
- **Sessions**: append-only JSONL under `~/.blazecode/sessions`; resume latest via `blazecode --resume`
- **Context**: project files, git state, and `AGENTS.md`
- **Todos**: multi-step task tracing when the agent needs it
- **Compaction**: keeps context lean on long chats

Nested selectors (`/models`, `/provider`, `/resume`) cancel with Ctrl+C and return to the prompt. At the main prompt, Ctrl+C exits cleanly.

---

## Configuration

```json
{
  "default_provider": "openai",
  "default_model": "gpt-5.6",
  "approval_mode": "on",
  "providers": [
    {
      "name": "openai",
      "base_url": "https://api.openai.com/v1",
      "api_key": "env:OPENAI_API_KEY",
      "models": ["gpt-5.6", "gpt-5.6-luna"]
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
| `on` | Confirm before every tool (default, safe) |
| `off` | Autonomous: run all tools without prompts |

Existing configs are migrated automatically: v2 `on` (autonomous) becomes `off`; v2 `off` (confirm all) becomes `on`. Older `ask`/`auto`/`plan` values normalize the same way.

---

## Terminal commands

Type `/` for fuzzy completion.

| Command | Purpose |
|---------|---------|
| `/status` | Provider, model, approval, tokens, mascot |
| `/approval on\|off` | Confirm every tool, or autonomous mode |
| `/provider` | Add or switch provider |
| `/models` | Switch models |
| `/export` | Export session to Markdown |
| `/clear` | Start a fresh session |
| `/resume` | Resume a saved session |
| `/exit` | Quit |

---

## Tools

| Tool | Role |
|------|------|
| `read` | Read a file (offset/limit) |
| `write` | Create or replace a file |
| `edit` | Exact string replacement |
| `bash` | Foreground shell command (timeout) |
| `grep` | Regex search |
| `todo` | Session task list for multi-step work |

Paths stay inside the working directory. When approval is `on`, every tool asks first.

Project guidance is loaded from `AGENTS.md` (nearest file up to the git root when present).

---

## Development

```bash
python -m pip install -e ".[dev]"
python -m pytest -q
python -m blazecode
```

---

## Uninstall notes

`install.sh --uninstall` (Linux/macOS) removes only the program (`~/.local/share/blazecode` and the `blazecode` link).  
`install.ps1 -Uninstall` (Windows) removes the venv (`%LOCALAPPDATA%\blazecode`), the `blazecode.cmd` shim, and its PATH entry.

Neither installer **ever** deletes `~/.blazecode`. To wipe user data:

```bash
rm -rf ~/.blazecode      # Linux/macOS
Remove-Item -Recurse -Force ~/.blazecode   # Windows PowerShell
```

---

## Troubleshooting

**Windows: `blazecode` is not recognized after install.**
Open a new terminal (PATH changes only apply to new processes). If still missing, check the shim dir is on your user PATH:
```powershell
[Environment]::GetEnvironmentVariable('Path','User') -split ';' | Select-String blazecode
```
If absent, re-run the installer, or add it manually:
```powershell
$dir = "$env:LOCALAPPDATA\blazecode\bin"
[Environment]::SetEnvironmentVariable('Path', "$dir;$([Environment]::GetEnvironmentVariable('Path','User'))", 'User')
```

**Windows: `running scripts is disabled on this machine`.**
The piped `irm | iex` command bypasses execution policy. If you run the local `install.ps1` file, allow it for the current session:
```powershell
Set-ExecutionPolicy -Scope Process -ExecutionPolicy Bypass
.\install.ps1
```

**Windows: installer reports "Python 3.11+ is required".**
Install Python 3.11+ (`winget install Python.Python.3.12`) or point the installer at a specific interpreter:
```powershell
$env:BLAZECODE_PYTHON = 'C:\Path\to\python.exe'
irm https://raw.githubusercontent.com/thealokverse/blazecode/main/install.ps1 | iex
```

**Windows: uninstall could not remove files.**
Close any running `blazecode` process, editors, or terminals holding the venv, then re-run `.\install.ps1 -Uninstall`. User data in `~/.blazecode` is always preserved.

**Update won't take effect.** Re-run the installer (it atomically swaps the venv aside and reinstalls). A running `blazecode` session keeps using the old process until you restart it.

---

## License

[MIT](./LICENSE)
