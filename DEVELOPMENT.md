# Development

Forward-looking notes for people working on Blazecode. This is not a promise list.

Blazecode should stay a small, fast terminal coding agent. The current architecture is the product: one loop, six tools, local sessions, optional approvals and skills.

## Current direction

v1.3.1 is a polish release: terminal feel, readability, and cleanup. The header box stays. The agent loop stays UI-neutral and small.

The next useful work is the same kind of work: make the existing path more reliable and easier to live in for long sessions.

## Planned

- Keep streaming, cancel, and recovery boringly reliable.
- Keep slash commands, approvals, trust, skills, and compaction as they are shaped today.
- Keep the header box and the `blaze (•‿•) ❯` prompt as the visual identity.
- Keep `loop.py` under 250 lines and `agent/` / `llm/` free of UI libraries.

## Exploring

- Better skill selection without loading skill bodies eagerly.
- Clearer compaction summaries when a session is long.
- Model list caching and ranking edge cases across providers.
- Quieter long-session history when resuming a large transcript.

These are worth trying if a concrete user problem shows up. They are not scheduled.

## Future

Not planned, and not accidental omissions:

- MCP
- Subagents
- IDE integration
- Plugin systems
- Extra toolkits beyond `read`, `write`, `edit`, `bash`, `grep`, `todo`

If Blazecode needs a new capability, prefer a smaller existing path over a new subsystem.

## Technical debt

- Git toplevel lookup is repeated in prompts, trust, skills, and repo map. Share it only if a bug appears.
- `llm.client.ToolResult` exists for the event union and is not emitted by the streamer.
- `ModelInfo` carries unused capability fields; ranking uses substring boosts instead.
- Approval mode still understands a few leftover legacy tokens at the manager boundary. Config migration already covers stored files.
- `summarize_history` and `/compact` both write `[context compacted]` notes; keep those prefixes aligned.

None of this needs a rewrite. Fix it when you are already in the file.

## Areas that need attention

- Provider quirks in `llm/client.py` (retries, tool_choice fallbacks, usage fields).
- Interactive cancel during tool execution, especially bash.
- Directory trust vs approval: two gates, easy to confuse in copy and tests.
- Windows installer PATH and Python launcher behavior.

## Ideas worth exploring

Only if they stay small:

- A slightly richer `/status` without becoming a dashboard.
- Export formats beyond Markdown.
- A documented skill-authoring example in the repo.

If an idea needs a new runtime, a new config language, or a second agent loop, it does not belong here.
