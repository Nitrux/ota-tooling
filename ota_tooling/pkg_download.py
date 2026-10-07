"""Package download helpers and CLI for OTA tooling.

The command reads a package-name list and downloads each package with APT, reusing files with matching checksums.
"""

from __future__ import annotations

import hashlib
import shutil
from pathlib import Path
import subprocess
import sys
from subprocess import CalledProcessError

from tqdm import tqdm

from .common import ensure_file_exists, ensure_valid_package_names, read_nonempty_lines


def _read_apt_package_metadata(packages):
    """Return APT filenames, sizes, and SHA-256 checksums for packages."""
    try:
        result = subprocess.run(
            ["apt-cache", "show", "--no-all-versions", *packages],
            stdout=subprocess.PIPE,
            stderr=subprocess.DEVNULL,
            text=True,
            check=False,
        )
    except OSError:
        return {}

    metadata = {}
    record = {}

    for line in (*result.stdout.splitlines(), ""):
        if not line:
            package = record.get("Package")
            filename = record.get("Filename")
            checksum = record.get("SHA256")
            size = record.get("Size")
            if package and filename and checksum:
                metadata[package] = (
                    Path(filename).name,
                    checksum.lower(),
                    int(size) if size and size.isdigit() else None,
                )
            record = {}
            continue

        if line[0].isspace() or ":" not in line:
            continue

        key, value = line.split(":", 1)
        record[key] = value.strip()

    return metadata


def _matches_apt_package(package, download_dir, metadata):
    """Check whether a downloaded package matches the expected checksum."""
    package_metadata = metadata.get(package)
    if not package_metadata:
        return False

    filename, expected_checksum, expected_size = package_metadata
    package_path = Path(download_dir) / filename

    try:
        if not package_path.is_file():
            return False
        if expected_size is not None and package_path.stat().st_size != expected_size:
            return False

        checksum = hashlib.sha256()
        with package_path.open("rb") as package_file:
            for chunk in iter(lambda: package_file.read(1024 * 1024), b""):
                checksum.update(chunk)
    except OSError:
        return False

    return checksum.hexdigest() == expected_checksum


def download_packages(package_list_file, download_dir):
    """Download packages listed in a text file using `apt download`.

    Args:
        package_list_file: Path to a file containing one package name per line.
        download_dir: Directory where downloaded packages should be stored.
    """
    ensure_file_exists(package_list_file, "Package list file")
    Path(download_dir).mkdir(parents=True, exist_ok=True)

    try:
        subprocess.run(
            ["sudo", "apt", "update"],
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            check=True,
        )
    except CalledProcessError:
        print("Failed to update package lists.")
        sys.exit(1)

    packages = read_nonempty_lines(package_list_file)
    ensure_valid_package_names(packages, "Package list file")
    apt_metadata = _read_apt_package_metadata(packages)
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
            if _matches_apt_package(package, download_dir, apt_metadata):
                skipped_packages += 1
                pbar.update(1)
                continue

            try:
                subprocess.run(
                    ["sudo", "apt", "download", package],
                    cwd=download_dir,
                    stdout=subprocess.DEVNULL,
                    stderr=subprocess.DEVNULL,
                    check=True,
                )
            except CalledProcessError:
                print(f"Package '{package}' not found. Exiting.")
                sys.exit(1)

            pbar.update(1)

    print("\nPackages downloaded successfully.")
    if skipped_packages:
        print(f"Skipped {skipped_packages} existing package(s) with matching checksums.")

