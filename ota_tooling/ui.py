"""Presentation helpers for the OTA workflow CLI.

The helpers in this module keep terminal output consistent across compare,
download, and archive creation.
"""

from __future__ import annotations

import os
import shutil
import sys
from dataclasses import dataclass
from typing import Iterable


@dataclass(frozen=True)
class SectionResult:
    """Small container for a stage name and its message lines."""

    title: str
    lines: tuple[str, ...]


class TerminalStyle:
    """ANSI style helper with a conservative color policy."""

    _RESET = "\033[0m"
    _BOLD = "\033[1m"
    _BLUE = "\033[34m"
    _GREEN = "\033[32m"
    _YELLOW = "\033[33m"
    _RED = "\033[31m"
    _CYAN = "\033[36m"

    def __init__(self, enabled: bool | None = None):
        if enabled is None:
            enabled = self._default_enabled()
        self.enabled = enabled

    @staticmethod
    def _default_enabled() -> bool:
        """Decide whether ANSI color should be enabled by default."""
        if os.environ.get("NO_COLOR"):
            return False
        return hasattr(sys.stderr, "isatty") and sys.stderr.isatty()

    def _wrap(self, text: str, color: str) -> str:
        if not self.enabled:
            return text
        return f"{self._BOLD}{color}{text}{self._RESET}"

    def header(self, text: str) -> str:
        """Format a stage header."""
        return self._wrap(text, self._CYAN)

    def success(self, text: str) -> str:
        """Format a success message."""
        return self._wrap(text, self._GREEN)

    def warning(self, text: str) -> str:
        """Format a warning message."""
        return self._wrap(text, self._YELLOW)

    def error(self, text: str) -> str:
        """Format an error message."""
        return self._wrap(text, self._RED)

    def label(self, text: str) -> str:
        """Format a label for key-value output."""
        return self._wrap(text, self._BLUE)


STYLE = TerminalStyle()


def write_line(text: str = "", *, stream=None) -> None:
    """Write a single line to the selected stream."""
    if stream is None:
        stream = sys.stderr
    print(text, file=stream)


def _rule(char: str = "-") -> str:
    """Return a horizontal rule sized for the current terminal width."""
    width = shutil.get_terminal_size(fallback=(72, 20)).columns
    return char * max(24, min(width, 72))


def section(title: str, *, stream=None) -> None:
    """Render a visual section header.

    Args:
        title: The section title.
        stream: Optional output stream.
    """
    write_line(stream=stream)
    write_line(_rule("="), stream=stream)
    write_line(f"{STYLE.header(title)}", stream=stream)
    write_line(_rule("-"), stream=stream)


def kv(label: str, value, *, stream=None) -> None:
    """Render a single key-value line.

    Args:
        label: The field name.
        value: The field value.
        stream: Optional output stream.
    """
    write_line(f"{STYLE.label(label):<18} {value}", stream=stream)


def bullet_list(items: Iterable[str], *, stream=None, prefix: str = "- ") -> None:
    """Render an iterable of items as a bullet list.

    Args:
        items: Items to render.
        stream: Optional output stream.
        prefix: Bullet prefix to use for each item.
    """
    for item in items:
        write_line(f"{prefix}{item}", stream=stream)


def announce_stage(title: str, subtitle: str | None = None) -> None:
    """Render a stage header with an optional subtitle."""
    section(title)
    if subtitle:
        write_line(subtitle)


def render_summary(title: str, lines: Iterable[tuple[str, object]]) -> None:
    """Render a compact summary block.

    Args:
        title: The summary title.
        lines: Iterable of ``(label, value)`` pairs.
    """
    section(title)
    for label, value in lines:
        kv(label, value)


def render_error(title: str, detail: str | None = None) -> None:
    """Render an error block."""
    section(STYLE.error(title))
    if detail:
        write_line(detail)
