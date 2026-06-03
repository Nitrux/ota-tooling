"""Package download helpers and CLI for OTA tooling.

The command reads a package-name list and downloads each package with APT.
"""

from __future__ import annotations

import shutil
from pathlib import Path
import subprocess
import sys
from subprocess import CalledProcessError

from tqdm import tqdm

from .common import ensure_file_exists, ensure_valid_package_names, read_nonempty_lines


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
    terminal_width = shutil.get_terminal_size().columns

    with tqdm(
        total=len(packages),
        desc="Downloading packages",
        unit="pkg",
        ncols=terminal_width,
        bar_format="{desc}: {percentage:3.0f}%|{bar}| {n_fmt}/{total_fmt} [{elapsed}<{remaining}]",
    ) as pbar:
        for package in packages:
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

