# Blazecode

Blazecode is a lightweight terminal coding agent written in Python. It streams
responses from OpenAI-compatible APIs, exposes exactly five code tools, and
keeps configuration and sessions in simple local files.

## Install

Python 3.11 or newer is required.

```bash
pipx install .
blazecode
```

The first launch opens a short provider wizard. It verifies the provider using
`GET /models`, asks for a model, and writes `~/.blazecode/config.json`.

Run one prompt without entering the REPL:

```bash
blazecode -p "Explain this repository"
```

Override a configured provider or model for one invocation:

```bash
blazecode --provider openrouter --model anthropic/claude-sonnet-4.6
```

## Providers and configuration

Blazecode v1 uses the OpenAI Chat Completions protocol. OpenAI, OpenRouter,
Groq, DeepSeek, Ollama, LM Studio, and compatible gateways use the same client.

```json
{
  "default_provider": "openai",
  "default_model": "gpt-4.1",
  "approval_mode": "ask",
  "providers": [
    {
      "name": "openai",
      "base_url": "https://api.openai.com/v1",
      "api_key": "env:OPENAI_API_KEY",
      "models": ["gpt-4.1", "gpt-4.1-mini"]
    },
    {
      "name": "local",
      "base_url": "http://localhost:11434/v1",
      "api_key": "none",
      "models": ["qwen2.5-coder:7b"]
    }
  ]
}
```

Use `env:VARIABLE` for keys when possible. A directly entered key is stored in
the configuration with `0600` permissions and is never printed in full.
`approval_mode` is `ask`, `auto`, or the read-only `plan`.

Use `/provider` to add or replace a provider and `/models` to switch models
without restarting. A custom provider needs a unique name, its API base URL,
and optionally an API key and fallback model list.

## Terminal commands

Typing `/` opens a fuzzy completion menu.

| Command | Purpose |
|---|---|
| `/help` | List commands |
| `/status` | Show provider, model, approval, tokens, and mascot state |
| `/provider` | Add or switch provider |
| `/models` | Switch models |
| `/skills` | List skills or install one with `/skills add <path>` |
| `/export` | Export the session to Markdown |
| `/clear` | Start a fresh session |
| `/resume` | Resume a saved JSONL session |
| `/exit` | Exit |

## Tools, skills, and project instructions

The model can call `read`, `write`, `edit`, `bash`, and `grep`. Read and search
stay within the launch directory. Write, edit, and bash pass through the single
approval gate. Bash commands are foreground-only and time-bounded.

Skills are directories containing `SKILL.md`. Blazecode discovers global
skills in `~/.blazecode/skills/` and project skills in
`./.blazecode/skills/`. Only names and descriptions enter the base prompt;
complete instructions are loaded when their terms match the current task.

An `AGENTS.md` or `BLAZECODE.md` in the launch directory is included as project
instructions.

## Development

```bash
python -m pip install -e '.[dev]'
pytest
```

Sessions are append-only JSONL files under `~/.blazecode/sessions/`.
