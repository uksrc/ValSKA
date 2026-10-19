"""Small helpers for terminal-oriented CLI formatting."""

from __future__ import annotations

import os
import sys
from argparse import ArgumentParser
from typing import Literal, TextIO, cast

from rich.console import Console
from rich.text import Text

ColorMode = Literal["auto", "always", "never"]
ProgressMode = Literal["auto", "always", "never"]

_STYLES = {
    "bold_cyan": "bold cyan",
    "dim": "dim",
    "green": "green",
    "red": "red",
    "yellow": "yellow",
}


class CliColors:
    """Apply Rich terminal styles when colour is enabled for a stream."""

    def __init__(
        self,
        mode: ColorMode = "auto",
        *,
        stream: TextIO | None = None,
        enabled: bool = True,
    ) -> None:
        self.mode = mode
        self.stream = stream if stream is not None else sys.stdout
        self.enabled = enabled and self._should_enable()
        self.console = Console(
            force_terminal=self.enabled,
            color_system="standard" if self.enabled else None,
            no_color=not self.enabled,
            file=self.stream,
        )

    def _should_enable(self) -> bool:
        if self.mode == "never":
            return False
        if os.environ.get("NO_COLOR") is not None:
            return False
        if self.mode == "always":
            return True
        return bool(getattr(self.stream, "isatty", lambda: False)())

    def style(self, text: object, style_name: str) -> str:
        value = str(text)
        if not self.enabled:
            return value
        rich_style = _STYLES.get(style_name)
        if rich_style is None:
            return value
        styled = Text(value, style=rich_style)
        with self.console.capture() as capture:
            self.console.print(styled, end="")
        return capture.get()

    def heading(self, text: object) -> str:
        return self.style(text, "bold_cyan")

    def path(self, text: object) -> str:
        return self.style(text, "green")

    def source(self, text: object) -> str:
        return self.style(f"[{text}]", "dim")

    def success(self, text: object) -> str:
        return self.style(text, "green")

    def error(self, text: object) -> str:
        return self.style(text, "red")

    def warning(self, text: object) -> str:
        return self.style(text, "yellow")


def add_color_argument(parser: ArgumentParser) -> None:
    """Add the standard ValSKA colour-mode option to a CLI parser."""
    parser.add_argument(
        "--color",
        choices=["auto", "always", "never"],
        default="auto",
        help=(
            "Colourise human-readable terminal output. "
            "Default: auto (enabled only for TTY output and disabled by NO_COLOR)."
        ),
    )


def add_progress_argument(parser: ArgumentParser) -> None:
    """Add the standard ValSKA progress-mode option to a CLI parser."""
    parser.add_argument(
        "--progress",
        choices=["auto", "always", "never"],
        default="auto",
        help=(
            "Show Rich progress output for long-running CLI steps. "
            "Default: auto (enabled only for interactive stderr)."
        ),
    )


def resolve_color_mode(raw: object) -> ColorMode:
    """Return a validated colour mode from argparse output."""
    if raw in ("auto", "always", "never"):
        return cast(ColorMode, raw)
    return "auto"


def resolve_progress_mode(raw: object) -> ProgressMode:
    """Return a validated progress mode from argparse output."""
    if raw in ("auto", "always", "never"):
        return cast(ProgressMode, raw)
    return "auto"


def show_progress(
    mode: ProgressMode, *, json_out: bool, stream: TextIO | None = None
) -> bool:
    """Return whether progress output should be displayed."""
    if json_out or mode == "never":
        return False
    if mode == "always":
        return True
    progress_stream = stream if stream is not None else sys.stderr
    return bool(getattr(progress_stream, "isatty", lambda: False)())
