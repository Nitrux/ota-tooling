"""Shared helpers for the OTA tooling CLI scripts.

This module holds small file-system and text utilities that are reused by the
package comparison and package download entry points.
"""

from __future__ import annotations

import os
import sys
from typing import Iterable


def ensure_file_exists(file_path: str, label: str) -> None:
    """Exit with a consistent error message if a file does not exist.

    Args:
        file_path: Path to the file that should exist.
        label: Human-readable label used in the error message.
    """
    if not os.path.exists(file_path):
        print(f"Error: {label} '{file_path}' not found.")
        sys.exit(1)


def ensure_directory_exists(directory: str, label: str) -> None:
    """Exit with a consistent error message if a directory does not exist.

    Args:
        directory: Path to the directory that should exist.
        label: Human-readable label used in the error message.
    """
    if not os.path.exists(directory):
        print(f"Error: {label} '{directory}' not found.")
        sys.exit(1)


def read_nonempty_lines(file_path: str) -> list[str]:
    """Read a text file and return stripped non-empty lines.

    Args:
        file_path: Path to the text file to read.

    Returns:
        A list of stripped, non-empty lines.
    """
    with open(file_path, "r", encoding="utf-8") as file:
        return [line.strip() for line in file if line.strip()]


def write_lines(lines: Iterable[str], file_path: str) -> None:
    """Write an iterable of lines to a file, one item per line.

    Args:
        lines: Iterable of strings to write.
        file_path: Destination file path.
    """
    with open(file_path, "w", encoding="utf-8") as file:
        for line in lines:
            file.write(f"{line}\n")
