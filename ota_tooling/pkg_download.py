"""Package download helpers and CLI for OTA tooling.

The command reads a package-name list and downloads each package with APT, reusing files with matching checksums.
"""

from __future__ import annotations

import hashlib
import shlex
import shutil
import tempfile
import time
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


def _read_apt_download_plan(packages):
    """Return the files APT would download for a package list."""
    result = subprocess.run(
        ["apt", "--print-uris", "download", *packages],
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
        check=False,
    )
    if result.returncode != 0:
        error = result.stderr.strip() or result.stdout.strip()
        raise RuntimeError(error or "APT could not resolve the packages.")

    plans = {}
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

        filename = Path(fields[1]).name
        package = filename.split("_", 1)[0]
        plans.setdefault(package, []).append(
            (filename, size, checksum_name.lower(), expected_checksum.lower())
        )

    if not plans:
        raise RuntimeError("APT did not report any package files.")

    return plans


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


def _completed_downloads(download_dir, packages, plans, initial_files):
    """Return packages whose planned files have finished downloading."""
    completed = set()

    if not plans:
        package_names = {
            package.split(":", 1)[0]: package for package in packages
        }
        for package_path in Path(download_dir).glob("*.deb"):
            package_name = package_path.name[:-4].rsplit("_", 2)[0]
            package = package_names.get(package_name)
            if package is None:
                continue
            try:
                stat_result = package_path.stat()
            except OSError:
                continue
            initial_state = initial_files.get(package_path)
            current_state = (stat_result.st_size, stat_result.st_mtime_ns)
            if initial_state is not None and current_state == initial_state:
                continue
            if stat_result.st_size > 0:
                completed.add(package)
        return completed

    for package in packages:
        plan = plans.get(package)
        if not plan:
            continue

        files_complete = True
        for filename, expected_size, _checksum_name, _expected_checksum in plan:
            package_path = Path(download_dir) / filename
            try:
                stat_result = package_path.stat()
            except OSError:
                files_complete = False
                break

            if stat_result.st_size != expected_size:
                files_complete = False
                break

            initial_state = initial_files.get(package_path)
            current_state = (stat_result.st_size, stat_result.st_mtime_ns)
            if initial_state is not None and current_state == initial_state:
                files_complete = False
                break

        if files_complete:
            completed.add(package)

    return completed


def _download_with_progress(download_dir, packages, plans, pbar):
    """Download packages with APT while tracking completed package files."""
    initial_files = {}
    for package_path in Path(download_dir).glob("*.deb"):
        try:
            stat_result = package_path.stat()
        except OSError:
            continue
        initial_files[package_path] = (
            stat_result.st_size,
            stat_result.st_mtime_ns,
        )

    completed = set()
    with tempfile.TemporaryFile(mode="w+t") as error_file:
        process = subprocess.Popen(
            ["apt", "download", *packages],
            cwd=download_dir,
            stdout=subprocess.DEVNULL,
            stderr=error_file,
            text=True,
        )

        while process.poll() is None:
            newly_completed = _completed_downloads(
                download_dir,
                packages,
                plans,
                initial_files,
            ) - completed
            if newly_completed:
                completed.update(newly_completed)
                pbar.update(len(newly_completed))
            time.sleep(0.1)

        returncode = process.wait()
        newly_completed = _completed_downloads(
            download_dir,
            packages,
            plans,
            initial_files,
        ) - completed
        if newly_completed:
            completed.update(newly_completed)
            pbar.update(len(newly_completed))

        error_file.seek(0)
        error = error_file.read().strip()

    return returncode, error, completed


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
    packages = [package for package in packages if "calamares" not in package]
    existing_packages = {path.name for path in Path(download_dir).glob("*.deb")}
    packages_to_download = packages
    skipped_packages = 0
    plans = {}

    if existing_packages and packages:
        packages_to_download = []
        try:
            plans = _read_apt_download_plan(packages)
        except RuntimeError as error:
            print(error, file=sys.stderr)
            print("Failed to plan package downloads. Exiting.")
            sys.exit(1)

        for package in packages:
            plan = plans.get(package)
            if not plan:
                print(f"APT did not report a package file for {package!r}.", file=sys.stderr)
                print(f"Failed to plan download for package {package!r}. Exiting.")
                sys.exit(1)

            if _matches_existing_package(download_dir, plan):
                skipped_packages += 1
            else:
                packages_to_download.append(package)

    terminal_width = shutil.get_terminal_size().columns

    with tqdm(
        total=len(packages),
        desc="Downloading packages",
        unit="pkg",
        ncols=terminal_width,
        bar_format="{desc}: {percentage:3.0f}%|{bar}| {n_fmt}/{total_fmt} [{elapsed}<{remaining}]",
    ) as pbar:
        pbar.update(skipped_packages)

        if packages_to_download:
            returncode, error, completed = _download_with_progress(
                download_dir,
                packages_to_download,
                plans,
                pbar,
            )
            if returncode != 0:
                if error:
                    print(error, file=sys.stderr)
                print("Failed to download packages. Exiting.")
                sys.exit(1)

            if len(completed) < len(packages_to_download):
                pbar.update(len(packages_to_download) - len(completed))
    print("\nPackages downloaded successfully.")
    if packages_to_download:
        print(f"Downloaded {len(packages_to_download)} new package(s).")
    if skipped_packages:
        print(f"Skipped {skipped_packages} existing package(s) with matching checksums.")

