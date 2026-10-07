"""OTA archive creation helpers.

This module ports the archive creation behavior into Python.
"""

from __future__ import annotations

import hashlib
import os
import shutil
import subprocess
import sys
from datetime import datetime
from pathlib import Path

from .ui import STYLE, render_summary

def emit(message: str, level: str = "info") -> None:
    """Print a compact status line with optional severity styling.

    Args:
        message: The message to emit.
        level: Log level used to choose the label.
    """
    if level == "success":
        print(STYLE.success("Success"), file=sys.stderr)
        return
    if level == "warning":
        line = f"{STYLE.warning('Warning')} {message}"
        print(line, file=sys.stderr)
        return
    if level == "error":
        line = f"{STYLE.error('Error')} {message}"
        print(line, file=sys.stderr)
        return

    line = f"{STYLE.label('Log')} {message}"
    print(line, file=sys.stderr)


def check_etc_paths(items):
    """Reject any source paths that live under ``/etc``.

    Args:
        items: Iterable of source paths to validate.
    """
    for item in items:
        if item.startswith("/etc"):
            emit("Paths from /etc are not allowed. Exiting.", "error")
            raise SystemExit(1)


def ensure_required_commands():
    """Verify that the external tools required for archive creation exist."""
    requirements = [
        ("mksquashfs", "'mksquashfs' command not found. Please make sure it's installed and try again."),
        ("unsquashfs", "'unsquashfs' command not found. Please make sure it's installed and try again."),
        ("sha256sum", "'sha256sum' command not found. Please make sure it's installed and try again."),
        ("du", "'du' command not found. Please make sure it's installed and try again."),
    ]
    for command, error_message in requirements:
        if shutil.which(command) is None:
            emit(error_message, "error")
            raise SystemExit(1)


def run_mksquashfs(items, dest_file):
    """Create the SquashFS archive with the expected compression settings.

    Args:
        items: Source paths to package into the archive.
        dest_file: Destination SquashFS file path.
    """
    cmd = [
        "mksquashfs",
        *items,
        dest_file,
        "-comp",
        "zstd",
        "-Xcompression-level",
        "22",
        "-b",
        "1048576",
        "-quiet",
        "-not-reproducible",
        "-no-strip",
        "-keep-as-directory",
    ]
    subprocess.run(cmd, check=True)


def list_squashfs_contents(dest_file):
    """Return the ``unsquashfs -l`` output for an archive.

    Args:
        dest_file: Path to the SquashFS archive.

    Returns:
        The text output from ``unsquashfs -l``.
    """
    cmd = ["unsquashfs", "-l", dest_file]
    proc = subprocess.run(cmd, check=True, capture_output=True, text=True)
    return proc.stdout


def sha256sum_file(file_path):
    """Compute the SHA256 digest for a file.

    Args:
        file_path: Path to the file to hash.

    Returns:
        The hexadecimal SHA256 digest string.
    """
    digest = hashlib.sha256()
    with open(file_path, "rb") as file:
        for chunk in iter(lambda: file.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def default_archive_name():
    """Return the default OTA archive name for the current timestamp."""
    return f"ota-{datetime.now().strftime('%Y.%m.%d-%H.%M')}-amd64.squashfs"


def create_archive(items, dest_file=None):
    """Create an OTA archive and its companion metadata files.

    Args:
        items: Source paths to include in the archive.
        dest_file: Optional explicit output archive path.

    Returns:
        A mapping describing the created archive and companion artifacts.
    """
    if os.geteuid() != 0:
        emit("Not running as root.", "error")
        raise SystemExit(1)

    if not items:
        emit("No directories or files specified.", "error")
        raise SystemExit(1)

    check_etc_paths(items)
    ensure_required_commands()

    if dest_file is None:
        dest_file = default_archive_name()

    Path(dest_file).expanduser().resolve().parent.mkdir(parents=True, exist_ok=True)

    try:
        run_mksquashfs(items, dest_file)
    except subprocess.CalledProcessError:
        emit("Failed to create SquashFS file.", "error")
        raise SystemExit(1)

    emit("", "success")

    contents = list_squashfs_contents(dest_file)
    contents_file = f"{dest_file}.contents"
    with open(contents_file, "w", encoding="utf-8") as file:
        file.write(contents)

    digest = sha256sum_file(dest_file)
    sha256_line = f"{digest}  {dest_file}"
    sha256_file = f"{dest_file}.sha256sum"
    with open(sha256_file, "w", encoding="utf-8") as file:
        file.write(f"{sha256_line}\n")

    size_output = subprocess.run(["du", "-sh", dest_file], check=True, capture_output=True, text=True).stdout.strip()
    human_size = size_output.split(maxsplit=1)[0] if size_output else size_output
    size = f"{Path(dest_file).stat().st_size} ({human_size})"

    render_summary(
        "Archive Summary",
        [
            ("Archive", dest_file),
            ("Checksum", digest),
            ("Contents", contents_file),
            ("SHA256 file", sha256_file),
            ("Size", size),
        ],
    )

    return {
        "archive": dest_file,
        "contents_file": contents_file,
        "sha256_file": sha256_file,
        "checksum": digest,
        "sha256_line": sha256_line,
        "size_output": size.rstrip("\n"),
    }
