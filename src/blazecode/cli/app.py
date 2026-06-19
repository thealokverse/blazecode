"""CLI entry point: argparse, first-run onboarding wizard, launch the REPL."""

from __future__ import annotations

import argparse
import asyncio
import sys
from typing import Sequence

from rich.console import Console

from blazecode import __version__
from blazecode.core.config import (
    CONFIG_PATH,
    Config,
    apply_env,
    load_config,
    save_config,
)
from blazecode.core.permissions import PermissionPolicy
from blazecode.engine.loop import build_agent
from blazecode.engine.session import Session
from blazecode.providers.registry import PROVIDERS, resolve_model
from blazecode.tools.registry import ToolRegistry
from blazecode.ui.terminal import FACE_IDLE, run_repl


HELP_TEXT = """\
>_ BlazeCode (v{version})

A lightweight, fast, terminal-based AI coding agent.

Usage:
  blazecode                       Start an interactive chat session.
                                  (Runs the onboarding wizard on first launch.)

  blazecode "your prompt here"    Headless mode: stream one turn to stdout
                                  and exit. Tools run, approvals auto-deny.

  blazecode -m openai/gpt-4o     Override the model from config.toml.

  blazecode --help                Show this help.
  blazecode --version             Show the version.

Inside the chat, type /help for all slash commands:
  /help, /status, /provider, /models, /skills,
  /export, /clear, /resume, /yolo, /exit
"""


def _parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(
        prog="blazecode",
        add_help=True,
        formatter_class=argparse.RawDescriptionHelpFormatter,
        description=HELP_TEXT.format(version=__version__),
    )
    p.add_argument(
        "prompt", nargs=argparse.REMAINDER,
        help="Headless mode: prompt to run non-interactively.",
    )
    p.add_argument("-m", "--model", help="Override model from config (e.g. openai/gpt-4o)")
    p.add_argument("--version", action="version", version=f"%(prog)s {__version__}")
    return p


# ---- onboarding helpers ----

def _prompt(prompt: str, *, secret: bool = False) -> str:
    if secret:
        try:
            from prompt_toolkit import prompt as _pt_prompt
            return _pt_prompt(prompt, is_password=True).strip()
        except Exception:
            pass
    try:
        return input(prompt).strip()
    except (EOFError, KeyboardInterrupt):
        print()
        return ""


def _select_number(prompt: str, options: list[str], *, default: int = 1) -> int:
    raw = _prompt(prompt)
    if not raw:
        return default
    try:
        idx = int(raw)
        if 1 <= idx <= len(options):
            return idx
    except ValueError:
        for i, opt in enumerate(options, 1):
            if raw.lower() == opt.lower():
                return i
    return default


# ---- onboarding wizard ----

def run_onboarding() -> Config:
    """Interactive first-time setup. Writes ~/.blazecode/config.toml and returns it."""
    console = Console()
    console.print()
    console.print("[bold]Welcome to Blazecode!![/] 🔥")
    console.print("Let's get set up.\n")

    console.print("[bold]Step 1:[/] Select Provider")
    provider_keys = list(PROVIDERS.keys())
    for i, k in enumerate(provider_keys, 1):
        info = PROVIDERS[k]
        marker = "  [dim](no key)[/]" if not info.needs_key else ""
        free = "  [green](free option available)[/]" if "free" in str(info.examples).lower() else ""
        console.print(f"  {i}. {info.name}{marker}{free}")
    console.print()
    chosen = provider_keys[_select_number("> ", provider_keys) - 1]
    info = PROVIDERS[chosen]

    api_key = ""
    if info.needs_key:
        console.print(f"\n[bold]Step 2:[/] Enter API Key (stored in {CONFIG_PATH}):")
        api_key = _prompt("> ", secret=True)
        if not api_key:
            console.print("[red]No key entered; aborting.[/]")
            sys.exit(1)
        console.print("  [dim]Tip: You can switch to a free model later with /models[/]")

    console.print(f"\n[bold]Step 3:[/] Select Model for {info.name}")
    for i, m in enumerate(info.examples, 1):
        free_tag = "  [green](free tier)[/]" if "free" in m.lower() else ""
        console.print(f"  {i}. {m}{free_tag}")
    console.print()
    chosen_model = info.examples[_select_number("> ", list(info.examples)) - 1]

    cfg = Config(model=chosen_model, permission="ask", max_iterations=25)
    if info.needs_key and api_key:
        cfg.provider_keys[chosen] = api_key
    save_config(cfg)
    apply_env(cfg)

    console.print(f"\n[green]✓ Setup complete![/] {FACE_IDLE}")
    console.print(f"  Provider: {info.name}")
    console.print(f"  Model:    {chosen_model}")
    if info.env_var:
        console.print(f"  API key stored in {CONFIG_PATH} ({info.env_var} now set).")
        if "free" not in chosen_model.lower():
            console.print("  [dim]Tip: Low on credits? Run /models and pick a free model.[/]")
    else:
        console.print(f"  No API key needed ({info.notes}).")
    console.print()
    return cfg


# ---- main ----

def _provider_label(model: str) -> str:
    if "/" in model:
        return model.split("/", 1)[0].lower()
    m = model.lower()
    if m.startswith("gpt"):
        return "openai"
    if m.startswith("claude"):
        return "anthropic"
    if m.startswith("gemini"):
        return "gemini"
    return "unknown"


def main(argv: Sequence[str] | None = None) -> int:
    args = _parser().parse_args(argv)  # exits cleanly on --help / --version

    try:
        cfg = load_config()
    except Exception as exc:
        print(f"blazecode: config error: {exc}", file=sys.stderr)
        return 2
    if not cfg.is_configured():
        cfg = run_onboarding()
    else:
        apply_env(cfg)

    # CLI --model flag overrides config
    if args.model:
        cfg.model = args.model

    try:
        model = resolve_model(cfg.model)
    except Exception as exc:
        print(f"blazecode: {exc}", file=sys.stderr)
        return 2

    agent = build_agent(
        model=model,
        session=Session(model=model, provider=_provider_label(model)),
        registry=ToolRegistry(),
        permission=PermissionPolicy(mode=cfg.permission),
        max_iterations=cfg.max_iterations,
    )

    prompt = " ".join(args.prompt).strip()
    if prompt:
        from blazecode.ui.terminal import run_headless
        try:
            return asyncio.run(run_headless(agent, prompt))
        except KeyboardInterrupt:
            return 130

    try:
        return asyncio.run(run_repl(agent))
    except KeyboardInterrupt:
        return 130


if __name__ == "__main__":
    raise SystemExit(main())
