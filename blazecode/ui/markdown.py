from __future__ import annotations

import re
from dataclasses import dataclass

from rich.console import Group, RenderableType
from rich.markdown import Markdown
from rich.syntax import Syntax
from rich.text import Text

from blazecode.ui.theme import DIFF_ADDED, DIFF_REMOVED, MUTED

_FENCE_RE = re.compile(r"^(`{3,}|~{3,})([^\n]*)\r?\n", re.MULTILINE)
_LANG_ALIASES = {
    "js": "javascript",
    "ts": "typescript",
    "py": "python",
    "rb": "ruby",
    "sh": "bash",
    "shell": "bash",
    "zsh": "bash",
    "yml": "yaml",
    "md": "markdown",
    "plaintext": "text",
    "txt": "text",
}


@dataclass(frozen=True, slots=True)
class _Fence:
    start: int
    marker: str
    lang: str
    body_start: int
    end: int | None


def split_stable(buffer: str, committed: int) -> tuple[str, str]:
    """Split uncommitted buffer into printable stable prefix and live pending suffix."""
    if committed < 0 or committed > len(buffer):
        committed = min(max(committed, 0), len(buffer))
    text = buffer[committed:]
    if not text:
        return "", ""

    fences = _find_fences(buffer)
    open_fence = next((f for f in fences if f.end is None and f.start >= committed), None)
    if open_fence is None:
        open_fence = next((f for f in fences if f.end is None), None)
        if open_fence is not None and open_fence.start < committed:
            return "", text

    if open_fence is not None and open_fence.start >= committed:
        stable = _trim_incomplete_line(buffer[committed : open_fence.start])
        return stable, buffer[committed + len(stable) :]

    if text.endswith("\n"):
        return text, ""
    last_nl = text.rfind("\n")
    if last_nl == -1:
        return "", text
    return text[: last_nl + 1], text[last_nl + 1 :]


def render_markdown(text: str) -> RenderableType:
    if not text:
        return Text("")
    if _looks_like_unified_diff(text):
        return render_diff(text)

    blocks = _split_fenced_blocks(text)
    if len(blocks) == 1 and blocks[0][0] == "prose":
        return _render_prose(blocks[0][1])

    parts: list[RenderableType] = []
    for block in blocks:
        kind, payload = block[0], block[1]
        if kind == "code":
            rendered = _render_code(payload, block[2] if len(block) > 2 else "")
            if rendered is not None:
                parts.append(rendered)
        elif kind == "diff":
            parts.append(render_diff(payload))
        elif payload.strip():
            parts.append(_render_prose(payload))
        elif payload:
            parts.append(Text(payload))
    if not parts:
        return Text("")
    if len(parts) == 1:
        return parts[0]
    return Group(*parts)


def render_partial(text: str) -> RenderableType:
    """Lightweight trailing preview for the status line — never a full Syntax panel."""
    if not text:
        return Text("")
    # one plain line only; avoids Live overflow painting dark code panels
    flat = text.replace("\r", "").expandtabs(4)
    line = flat.split("\n")[-1] if "\n" in flat else flat
    if len(line) > 100:
        line = "…" + line[-99:]
    return Text(line, style=MUTED)


def render_diff(diff: str) -> Text:
    output = Text()
    for index, line in enumerate(diff.splitlines()):
        if index:
            output.append("\n")
        if line.startswith("+++") or line.startswith("---"):
            output.append(line, style="bold")
        elif line.startswith("@@"):
            output.append(line, style="cyan")
        elif line.startswith("+"):
            output.append(line, style=DIFF_ADDED)
        elif line.startswith("-"):
            output.append(line, style=DIFF_REMOVED)
        else:
            output.append(line, style=MUTED)
    return output


def _trim_incomplete_line(text: str) -> str:
    if not text or text.endswith("\n"):
        return text
    last_nl = text.rfind("\n")
    if last_nl == -1:
        return ""
    return text[: last_nl + 1]


def _find_fences(text: str) -> list[_Fence]:
    fences: list[_Fence] = []
    pos = 0
    while True:
        match = _FENCE_RE.search(text, pos)
        if not match:
            break
        marker = match.group(1)
        lang = _normalize_lang(match.group(2))
        body_start = match.end()
        close = _find_closing_fence(text, body_start, marker)
        if close is None:
            fences.append(_Fence(match.start(), marker, lang, body_start, None))
            break
        fences.append(_Fence(match.start(), marker, lang, body_start, close))
        pos = close
    return fences


def _find_closing_fence(text: str, body_start: int, marker: str) -> int | None:
    pattern = re.compile(rf"^({re.escape(marker)})[ \t]*\r?$", re.MULTILINE)
    match = pattern.search(text, body_start)
    if not match:
        return None
    end = match.end()
    if end < len(text) and text[end] == "\n":
        end += 1
    return end


def _split_fenced_blocks(text: str) -> list[tuple]:
    fences = _find_fences(text)
    if not fences:
        return [("prose", text)]

    blocks: list[tuple] = []
    cursor = 0
    for fence in fences:
        if fence.start > cursor:
            blocks.append(("prose", text[cursor : fence.start]))
        if fence.end is None:
            body = _normalize_code_body(text[fence.body_start :])
            if fence.lang == "diff" or _looks_like_unified_diff(body):
                blocks.append(("diff", body))
            else:
                blocks.append(("code", body, fence.lang))
            cursor = len(text)
            break
        body = text[fence.body_start : fence.end]
        body = re.sub(rf"\n?{re.escape(fence.marker)}[ \t]*\r?\n?$", "", body)
        body = _normalize_code_body(body)
        if fence.lang == "diff" or _looks_like_unified_diff(body):
            blocks.append(("diff", body))
        else:
            blocks.append(("code", body, fence.lang))
        cursor = fence.end
    if cursor < len(text):
        blocks.append(("prose", text[cursor:]))
    return blocks


def _normalize_code_body(code: str) -> str:
    # drop trailing blank lines that become empty numbered / black rows
    return code.replace("\r\n", "\n").replace("\r", "\n").rstrip("\n")


def _render_prose(text: str) -> RenderableType:
    if not text.strip():
        return Text(text)
    if not _needs_markdown(text):
        return Text(text.rstrip("\n"))
    # no code_theme: fenced blocks are handled separately; avoid monokai panels
    return Markdown(text, hyperlinks=False)


def _needs_markdown(text: str) -> bool:
    markers = ("**", "__", "](", "* ", "- ", "# ", "> ", "1. ", "\n|", "~~")
    stripped = text.lstrip()
    if stripped.startswith(("#", ">", "-", "*", "|")):
        return True
    # bare backticks alone are fine as plain text; avoid Markdown width padding
    if "`" in text and any(m in text for m in ("**", "__", "](", "\n-", "\n*", "\n#")):
        return True
    return any(marker in text for marker in markers)


def _render_code(
    code: str, lang: str, *, line_numbers: bool = True
) -> RenderableType | None:
    body = _normalize_code_body(code)
    if not body.strip():
        return None
    language = lang or "text"
    try:
        return Syntax(
            body,
            language,
            theme="monokai",
            line_numbers=line_numbers,
            word_wrap=True,
            background_color="default",
            padding=0,
        )
    except Exception:
        return Text(body)


def _normalize_lang(raw: str) -> str:
    token = (raw or "").strip().split()[0] if (raw or "").strip() else ""
    token = token.lower().strip("{}")
    return _LANG_ALIASES.get(token, token)


def _looks_like_unified_diff(text: str) -> bool:
    lines = [line for line in text.splitlines() if line.strip()]
    if len(lines) < 2:
        return False
    heads = 0
    changes = 0
    for line in lines[:40]:
        if line.startswith(("diff ", "--- ", "+++ ")):
            heads += 1
        elif line.startswith("@@ ") or (
            line[:1] in "+-" and not line.startswith(("+++", "---"))
        ):
            changes += 1
    return heads >= 1 and changes >= 1
