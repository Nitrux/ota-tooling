"""Comparison helpers and CLI for OTA package list diffs.

The command compares two ``dpkg -l``-style lists and writes updated, new, and
removed package lists, plus optional NVIDIA-specific subsets.
"""

from __future__ import annotations

import re
import subprocess
import sys
import tarfile

from .common import ensure_file_exists, write_lines


NVIDIA_PATTERNS = [
    r"nvidia",
    r"libnvidia",
    r"libcuda",
    r"cuda",
    r"nvcuvid",
    r"nvoptix",
    r"cudadebugger",
]


def load_package_list(file_path):
    """Load a dpkg-style package list file into a name-to-version mapping.

    Args:
        file_path: Path to the package list file.

    Returns:
        A mapping of package name to version string.
    """
    ensure_file_exists(file_path, "The package list file")

    packages = {}
    try:
        with open(file_path, "r", encoding="utf-8") as file:
            for line in file:
                if line.startswith("ii"):
                    parts = line.split()
                    if len(parts) >= 3:
                        package_name = parts[1].replace(":amd64", "")
                        package_version = parts[2]
                        packages[package_name] = package_version
    except PermissionError:
        print(f"Error: Permission denied reading '{file_path}'.")
        sys.exit(1)
    except Exception as e:
        print(f"Error reading '{file_path}': {e}")
        sys.exit(1)

    return packages


def compare_package_lists(list_a, list_b):
    """Compare two package lists and classify version changes and presence.

    Args:
        list_a: Reference package mapping.
        list_b: Comparison package mapping.

    Returns:
        A tuple containing updated, new, and removed package names.
    """
    newer_versions = {}
    only_in_b = {}
    removed_packages = {}

    for package, version in list_b.items():
        if package in list_a:
            if version != list_a[package]:
                newer_versions[package] = version
        else:
            only_in_b[package] = version

    for package in list_a:
        if package not in list_b:
            removed_packages[package] = list_a[package]

    return (
        list(newer_versions.keys()),
        list(only_in_b.keys()),
        list(removed_packages.keys()),
    )


def remove_excluded_packages(packages, exclude_list, exclude_patterns):
    """Filter out packages that match explicit names or regex patterns.

    Args:
        packages: Iterable of package names to filter.
        exclude_list: Exact package names to remove.
        exclude_patterns: Regex patterns for packages to remove.

    Returns:
        A filtered list of package names.
    """
    return [
        package
        for package in packages
        if package not in exclude_list
        and not any(re.search(pattern, package) for pattern in exclude_patterns)
    ]


def save_packages_to_file(packages, file_name):
    """Write a package list to a file, one package per line.

    Args:
        packages: Iterable of package names to write.
        file_name: Destination file path.
    """
    write_lines(sorted(set(packages)), file_name)


def _parse_relation_names(value):
    """Parse a Debian relation field into a set of package names.

    Args:
        value: Raw relation field text from dpkg metadata.

    Returns:
        A set of package names extracted from the field.
    """
    if not value:
        return set()

    value = value.replace("\n", " ")
    items = [v.strip() for v in value.split(",") if v.strip()]

    pkgs = set()
    for item in items:
        alts = [a.strip() for a in item.split("|") if a.strip()]
        for alt in alts:
            name = alt.split("(", maxsplit=1)[0].strip()
            if name:
                pkgs.add(name)
    return pkgs


def parse_dpkg_status_bytes(data):
    """Parse the contents of a dpkg status file into metadata for each package.

    Args:
        data: Raw bytes from a dpkg status file.

    Returns:
        A mapping of package name to Replaces/Provides metadata.
    """
    text = data.decode("utf-8", errors="replace")
    stanzas = [s for s in text.split("\n\n") if s.strip()]
    meta = {}

    for stanza in stanzas:
        current_key = None
        fields = {}
        for line in stanza.splitlines():
            if not line:
                continue
            if line[0].isspace() and current_key:
                fields[current_key] = (
                    fields.get(current_key, "") + "\n" + line.strip()
                )
                continue
            if ":" not in line:
                continue
            k, v = line.split(":", 1)
            current_key = k.strip()
            fields[current_key] = v.lstrip()

        pkg = fields.get("Package")
        if not pkg:
            continue

        replaces = _parse_relation_names(fields.get("Replaces", ""))
        provides = _parse_relation_names(fields.get("Provides", ""))

        meta[pkg] = {"Replaces": replaces, "Provides": provides}

    return meta


def load_dpkg_metadata_from_tar(tar_path):
    """Load dpkg status metadata from a tar archive containing /var/lib/dpkg.

    Args:
        tar_path: Path to the tar archive to inspect.

    Returns:
        A metadata mapping compatible with :func:`parse_dpkg_status_bytes`.
    """
    ensure_file_exists(tar_path, "The archive")

    candidates = [
        "/var/lib/dpkg/status",
        "var/lib/dpkg/status",
        "./var/lib/dpkg/status",
    ]

    try:
        with tarfile.open(tar_path, "r:*") as tf:
            members = {m.name: m for m in tf.getmembers()}

            status_member = None
            for c in candidates:
                if c in members and members[c].isfile():
                    status_member = members[c]
                    break

            if status_member is None:
                expected = ", ".join(candidates)
                print(
                    "Error: Could not find a readable dpkg status file in "
                    f"'{tar_path}'. Expected one of: {expected}."
                )
                sys.exit(1)

            f = tf.extractfile(status_member)
            if f is None:
                print(
                    "Error: Found dpkg status entry "
                    f"'{status_member.name}' in '{tar_path}', but it could not be read."
                )
                sys.exit(1)

            data = f.read()
            return parse_dpkg_status_bytes(data)

    except tarfile.ReadError:
        print(f"Error: '{tar_path}' is not a valid tar archive.")
        sys.exit(1)


def get_control_data_from_host(package_name):
    """Query dpkg on the host for Replaces/Provides metadata of a package.

    Args:
        package_name: Package name to query with ``dpkg-query``.

    Returns:
        A mapping with ``Replaces`` and ``Provides`` sets.
    """
    try:
        proc = subprocess.run(
            ["dpkg-query", "-W", "-f=${Replaces}\n${Provides}\n", package_name],
            check=True,
            stdout=subprocess.PIPE,
            stderr=subprocess.DEVNULL,
            text=True,
        )
        lines = proc.stdout.splitlines()
        replaces_raw = lines[0].strip() if len(lines) >= 1 else ""
        provides_raw = lines[1].strip() if len(lines) >= 2 else ""
    except (FileNotFoundError, subprocess.CalledProcessError):
        replaces_raw = ""
        provides_raw = ""

    return {
        "Replaces": _parse_relation_names(replaces_raw),
        "Provides": _parse_relation_names(provides_raw),
    }


def build_transition_index(list_packages, dpkg_meta=None):
    """Build reverse indexes from snapshot metadata for transition filtering.

    Args:
        list_packages: Package mapping from the old or new snapshot.
        dpkg_meta: Optional metadata mapping for packages in that snapshot.

    Returns:
        A tuple of reverse indexes for ``Replaces`` and ``Provides`` matches.
    """
    replaces_index = {}
    provides_index = {}

    for pkg in list_packages.keys():
        if dpkg_meta is not None:
            md = dpkg_meta.get(pkg, {"Replaces": set(), "Provides": set()})
        else:
            md = get_control_data_from_host(pkg)

        for r in md.get("Replaces", set()):
            replaces_index.setdefault(r, set()).add(pkg)

        for p in md.get("Provides", set()):
            provides_index.setdefault(p, set()).add(pkg)

    return replaces_index, provides_index


def classify_nvidia_packages(packages, patterns):
    """Return packages related to NVIDIA by package name.

    Args:
        packages: Iterable of package names to inspect.
        patterns: Regex patterns that identify NVIDIA-related names.

    Returns:
        A sorted list of NVIDIA-related package names.
    """
    result = set()
    for pkg in packages:
        if any(re.search(pattern, pkg) for pattern in patterns):
            result.add(pkg)

    return sorted(result)

