"""Package download helpers and CLI for OTA tooling.

The command reads a package-name list and downloads each package with APT, reusing files with matching checksums.
"""

from __future__ import annotations

import hashlib
import shlex
import shutil
from pathlib import Path
import subprocess
import sys

from tqdm import tqdm

from .common import ensure_file_exists, ensure_valid_package_names, read_nonempty_lines


def _ensure_apt_available():
    """Exit with a clear error when a required APT command is unavailable."""
    required_commands = ("apt",)
    missing_commands = [
        command for command in required_commands if shutil.which(command) is None
    ]
    if missing_commands:
        missing = ", ".join(missing_commands)
        print(f"Error: required command(s) not found: {missing}.", file=sys.stderr)
        sys.exit(1)


def _read_apt_download_plan(package):
    """Return the package files APT would download without fetching them."""
    result = subprocess.run(
        ["apt", "--print-uris", "download", package],
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
        check=False,
    )
    if result.returncode != 0:
        error = result.stderr.strip() or result.stdout.strip()
        raise RuntimeError(error or "APT could not resolve the package.")

    plan = []
    for line in result.stdout.splitlines():
        fields = shlex.split(line)
        if len(fields) < 4 or not fields[1].endswith(".deb"):
            continue
        checksum_name, separator, expected_checksum = fields[3].partition(":")
        if not separator or checksum_name.lower() not in ("md5sum", "sha1", "sha256", "sha512"):
            continue
        try:
            size = int(fields[2])
        except ValueError:
            continue
        plan.append((Path(fields[1]).name, size, checksum_name.lower(), expected_checksum.lower()))

    if not plan:
        raise RuntimeError("APT did not report a package file.")

    return plan


def _matches_existing_package(download_dir, plan):
    """Check whether all files in an APT download plan are already valid."""
    for filename, expected_size, checksum_name, expected_checksum in plan:
        package_path = Path(download_dir) / filename
        try:
            if not package_path.is_file() or package_path.stat().st_size != expected_size:
                return False

            checksum = hashlib.new(checksum_name)
            with package_path.open("rb") as package_file:
                for chunk in iter(lambda: package_file.read(1024 * 1024), b""):
                    checksum.update(chunk)
        except OSError:
            return False

        if checksum.hexdigest() != expected_checksum:
            return False

    return True


def download_packages(package_list_file, download_dir):
    """Download packages listed in a text file using `apt download`.

    Args:
        package_list_file: Path to a file containing one package name per line.
        download_dir: Directory where downloaded packages should be stored.
    """
    _ensure_apt_available()
    ensure_file_exists(package_list_file, "Package list file")
    Path(download_dir).mkdir(parents=True, exist_ok=True)

    packages = read_nonempty_lines(package_list_file)
    ensure_valid_package_names(packages, "Package list file")
    existing_packages = {path.name for path in Path(download_dir).glob("*.deb")}
    skipped_packages = 0
    terminal_width = shutil.get_terminal_size().columns

    with tqdm(
        total=len(packages),
        desc="Downloading packages",
        unit="pkg",
        ncols=terminal_width,
        bar_format="{desc}: {percentage:3.0f}%|{bar}| {n_fmt}/{total_fmt} [{elapsed}<{remaining}]",
    ) as pbar:
        for package in packages:
            if existing_packages:
                try:
                    plan = _read_apt_download_plan(package)
                except RuntimeError as error:
                    print(error, file=sys.stderr)
                    print(f"Failed to plan download for package {package!r}. Exiting.")
                    sys.exit(1)

                if _matches_existing_package(download_dir, plan):
                    skipped_packages += 1
                    pbar.update(1)
                    continue

            download_result = subprocess.run(
                ["apt", "download", package],
                cwd=download_dir,
                stdout=subprocess.DEVNULL,
                stderr=subprocess.PIPE,
                text=True,
                check=False,
            )
            if download_result.returncode != 0:
                error = download_result.stderr.strip()
                if error:
                    print(error, file=sys.stderr)
                print(f"Failed to download package '{package}'. Exiting.")
                sys.exit(1)

            pbar.update(1)

    print("\nPackages downloaded successfully.")
    if skipped_packages:
        print(f"Skipped {skipped_packages} existing package(s) with matching checksums.")

