"""Consistent, colour-aware console output for every lab.

Why this exists
---------------
Lab 1 prints a different kind of event — a model turn, a tool call.
"""

from __future__ import annotations

import os
import sys
import json
import shutil
from typing import Any

# --- colour handling -------------------------------------------------------

_USE_COLOR = sys.stdout.isatty() and not os.environ.get("NO_COLOR")


def _c(code: str, text: str) -> str:
    """Wrap `text` in an ANSI colour `code`, or return it bare if colour is off."""
    return f"\033[{code}m{text}\033[0m" if _USE_COLOR else text


def dim(t: str) -> str:
    return _c("2", t)


def bold(t: str) -> str:
    return _c("1", t)


def cyan(t: str) -> str:
    return _c("36", t)


def green(t: str) -> str:
    return _c("32", t)


def yellow(t: str) -> str:
    return _c("33", t)


def red(t: str) -> str:
    return _c("31", t)


def magenta(t: str) -> str:
    return _c("35", t)


def blue(t: str) -> str:
    return _c("34", t)


# --- layout ----------------------------------------------------------------

def width(default: int = 78) -> int:
    """Terminal width, clamped so output stays readable in wide windows."""
    return min(shutil.get_terminal_size((default, 24)).columns, 96)


def rule(char: str = "-") -> None:
    print(dim(char * width()))


def banner(lab: str, title: str, subtitle: str = "") -> None:
    """Header printed once at the top of every lab run.

    `lab` is the roadmap position (e.g. "LAB 5"), `title` the lab name, and
    `subtitle` the one-line statement of what this run is meant to prove.
    """
    print()
    print(dim("=" * width()))
    print(f"  {bold(cyan(lab))}  {bold(title)}")
    if subtitle:
        print(f"  {dim(subtitle)}")
    print(dim("=" * width()))


def section(text: str) -> None:
    """A numbered or named phase within a lab run."""
    print()
    print(f"{bold(blue('>>'))} {bold(text)}")


# --- agent / tool events ---------------------------------------------------
#
# Every event line is rendered as a fixed-width tag column followed by the
# message, so transcripts stay aligned no matter which lab produced them.
# Padding is computed on the *uncoloured* tag — ANSI escapes have no width but
# do have length, so str.ljust() on a coloured string would misalign.

_TAG_COL = 13


def _emit(tag: str, paint, msg: str, stream=None) -> None:
    pad = " " * max(1, _TAG_COL - len(tag))
    print(f"{bold(paint(tag))}{pad}{msg}", file=stream or sys.stdout)


def user(text: str) -> None:
    """The prompt handed to the agent."""
    _emit("[user]", magenta, text)


def agent(text: str) -> None:
    """Final natural-language answer from the model."""
    _emit("[agent]", cyan, text)


def thinking(text: str) -> None:
    """Narration of what the harness is doing between model turns."""
    _emit("[..]", dim, dim(text))


def tool_call(name: str, args: Any = None) -> None:
    """The model asked to run a tool. Printed *before* any policy check."""
    rendered = ""
    if args:
        rendered = json.dumps(args, sort_keys=True)
        if len(rendered) > 110:
            rendered = rendered[:107] + "..."
        rendered = f" {dim(rendered)}"
    _emit("[tool]", yellow, f"{bold(name)}{rendered}")


def tool_result(text: str, is_error: bool = False) -> None:
    """What came back over the wire from the MCP server."""
    tag, paint = ("[error]", red) if is_error else ("[result]", green)
    body = text if len(text) <= 400 else text[:397] + "..."
    lines = body.splitlines() or [""]
    _emit(tag, paint, lines[0])
    for line in lines[1:]:
        print(f"{' ' * _TAG_COL}{line}")


# --- misc ------------------------------------------------------------------

def kv(label: str, value: Any, indent: int = 0) -> None:
    """Aligned key/value line, for run configuration and summaries."""
    pad = " " * indent
    print(f"{pad}{dim(label.ljust(22 - indent))} {value}")


def note(text: str) -> None:
    print(f"{dim('note:')} {dim(text)}")


def warn(text: str) -> None:
    print(f"{bold(yellow('warn:'))} {text}")


def error(text: str) -> None:
    print(f"{bold(red('error:'))} {text}", file=sys.stderr)


def takeaway(lines: list[str]) -> None:
    """Closing block: what this lab just demonstrated, and what it exposed.

    Every lab ends with one of these so the roadmap reads as a narrative
    rather than nine disconnected scripts.
    """
    print()
    rule("=")
    print(f"  {bold('TAKEAWAY')}")
    for line in lines:
        print(f"    {bold(dim('*'))} {line}")
    rule("=")
    print()
