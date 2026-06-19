"""Module entry point: ensure API keys are loaded before anything else, then run CLI."""

from __future__ import annotations

# IMPORTANT: load config + apply env vars to os.environ BEFORE any other
# blazecode imports (which transitively import the OpenAI SDK). This
# guarantees the SDK sees the keys from the first request onward.
from blazecode.core.config import apply_env, load_config

try:
    _cfg = load_config()
    apply_env(_cfg)
except Exception:
    # Config may not exist yet (first run -> onboarding) — that's fine.
    pass


def main() -> int:
    from blazecode.cli.app import main as _main
    return _main()


raise SystemExit(main())
