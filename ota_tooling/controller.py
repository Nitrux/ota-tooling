"""Top-level OTA workflow controller.

This module exposes the main ``ota-build`` command, which can compare
package lists, download the required packages, or create the archive.
"""

from __future__ import annotations

import argparse
from pathlib import Path

from . import archive, pkg_compare, pkg_download
from .ui import announce_stage, render_summary


def _add_compare_arguments(parser: argparse.ArgumentParser) -> None:
    """Add pkg-compare compatible arguments to a parser."""
    parser.add_argument(
        "list_a",
        metavar="list1.txt",
        help="Path to the first package list to compare.",
    )
    parser.add_argument(
        "list_b",
        metavar="list2.txt",
        help="Path to the second package list to compare.",
    )
    parser.add_argument(
        "--output-dir",
        default=".",
        help=(
            "Directory where compare outputs will be written. "
            "Defaults to the current directory."
        ),
    )
    parser.add_argument(
        "-u",
        "--out-updated",
        metavar="update_list.txt",
        help=(
            "File name for saving packages with newer versions. "
            "Defaults to updates_<baseline>.txt."
        ),
    )
    parser.add_argument(
        "-n",
        "--out-new",
        metavar="new_list.txt",
        help=(
            "File name for saving packages only in the second list. "
            "Defaults to new_<baseline>.txt."
        ),
    )
    parser.add_argument(
        "-r",
        "--out-removed",
        metavar="removed_list.txt",
        help=(
            "File name for saving packages removed from the second list. "
            "Defaults to removed_<baseline>.txt."
        ),
    )
    parser.add_argument(
        "--var-db-old",
        metavar="var-lib-dpkg-old.tar.xz",
        help=(
            "TAR archive containing /var/lib/dpkg from the rootfs snapshot "
            "used to generate list A."
        ),
    )
    parser.add_argument(
        "--var-db-new",
        metavar="var-lib-dpkg-new.tar.xz",
        help=(
            "TAR archive containing /var/lib/dpkg from the rootfs snapshot "
            "used to generate list B."
        ),
    )
    parser.add_argument(
        "--nv-new",
        metavar="nv_new_list.txt",
        help=(
            "File name for saving NVIDIA-related packages only in the second list. "
            "Defaults to nv_new_<baseline>.txt."
        ),
    )
    parser.add_argument(
        "--nv-update",
        metavar="nv_updated_list.txt",
        help=(
            "File name for saving NVIDIA-related packages with newer versions. "
            "Defaults to nv_updates_<baseline>.txt."
        ),
    )
    parser.add_argument(
        "--nv-remove",
        metavar="nv_removed_list.txt",
        help=(
            "File name for saving NVIDIA-related packages removed from the second list. "
            "Defaults to nv_removed_<baseline>.txt."
        ),
    )
    parser.add_argument(
        "--dry-run",
        "--show-plan",
        action="store_true",
        dest="preview",
        help="Show the plan and computed counts without writing files.",
    )

def _add_download_arguments(parser: argparse.ArgumentParser) -> None:
    """Add pkg-download compatible arguments to a parser."""
    parser.add_argument(
        "file",
        help="Path to the package list file.",
    )
    parser.add_argument(
        "--output-dir",
        default=".",
        help="Directory to download packages to. Defaults to the current directory.",
    )

def _add_create_arguments(parser: argparse.ArgumentParser) -> None:
    """Add archive creation arguments to a parser."""
    parser.add_argument(
        "items",
        nargs="+",
        help="Directories or files to include in the OTA archive.",
    )
    parser.add_argument(
        "--output",
        help="Optional output SquashFS file name.",
    )


def _baseline_tag(path: str) -> str:
    """Return the release tag embedded in a build list filename."""
    name = Path(path).name
    stem = Path(path).stem
    if "-" in stem:
        suffix = stem.split("-", 1)[1].strip()
        if suffix:
            return suffix
    return name


def _compare_output_names(tag: str, *, override_updated, override_new, override_removed, override_nv_new, override_nv_update, override_nv_remove, nvidia_enabled: bool) -> dict[str, str | None]:
    """Build output filenames for a compare run."""
    outputs = {
        "updated": override_updated or f"updates_{tag}.txt",
        "new": override_new or f"new_{tag}.txt",
        "removed": override_removed or f"removed_{tag}.txt",
    }
    if nvidia_enabled:
        outputs.update({
            "nv_updated": override_nv_update or f"nv_updates_{tag}.txt",
            "nv_new": override_nv_new or f"nv_new_{tag}.txt",
            "nv_removed": override_nv_remove or f"nv_removed_{tag}.txt",
        })
    else:
        outputs.update({"nv_updated": None, "nv_new": None, "nv_removed": None})
    return outputs


def _compare_baseline_tag(args) -> str:
    """Return the baseline tag for a compare run and validate it matches."""
    tag_a = _baseline_tag(args.list_a)
    tag_b = _baseline_tag(args.list_b)
    if tag_a != tag_b:
        raise SystemExit(
            f"Error: mixed baselines are not allowed ('{tag_a}' vs '{tag_b}')."
        )
    return tag_a


def _compare_state(args, *, nvidia_enabled: bool) -> dict[str, list[str]]:
    """Compute filtered compare outputs and NVIDIA-specific subsets."""
    list_a = pkg_compare.load_package_list(args.list_a)
    list_b = pkg_compare.load_package_list(args.list_b)

    newer_versions, only_in_b, removed_packages = pkg_compare.compare_package_lists(
        list_a,
        list_b,
    )

    dpkg_meta_a = None
    dpkg_meta_b = None

    if args.var_db_old:
        dpkg_meta_a = pkg_compare.load_dpkg_metadata_from_tar(args.var_db_old)
    if args.var_db_new:
        dpkg_meta_b = pkg_compare.load_dpkg_metadata_from_tar(args.var_db_new)

    if dpkg_meta_a is not None:
        old_replaces_index, old_provides_index = pkg_compare.build_transition_index(
            list_a,
            dpkg_meta_a,
        )
        filtered_new = []
        for new_pkg in only_in_b:
            if new_pkg in old_replaces_index or new_pkg in old_provides_index:
                continue
            filtered_new.append(new_pkg)
    else:
        filtered_new = list(only_in_b)

    if dpkg_meta_b is not None:
        replaces_index, provides_index = pkg_compare.build_transition_index(
            list_b,
            dpkg_meta_b,
        )
        real_removals = []
        for removed_pkg in removed_packages:
            if removed_pkg in replaces_index or removed_pkg in provides_index:
                continue
            real_removals.append(removed_pkg)
    else:
        real_removals = list(removed_packages)

    exclude_list = [
        "apt",
        "apt-transport-https",
        "calamares",
        "calamares-qml-settings-nitrux",
        "casper",
    ]
    exclude_patterns = [
        r"dpkg",
        r"libapt-pkg",
        r"systemd",
        *pkg_compare.NVIDIA_PATTERNS,
    ]
    nvidia_patterns = pkg_compare.NVIDIA_PATTERNS

    if nvidia_enabled:
        nv_updated = pkg_compare.classify_nvidia_packages(
            newer_versions,
            nvidia_patterns,
        )
        nv_new = pkg_compare.classify_nvidia_packages(
            filtered_new,
            nvidia_patterns,
        )
        nv_removed = pkg_compare.classify_nvidia_packages(
            real_removals,
            nvidia_patterns,
        )
    else:
        nv_updated = []
        nv_new = []
        nv_removed = []

    return {
        "updated": pkg_compare.remove_excluded_packages(
            newer_versions,
            exclude_list,
            exclude_patterns,
        ),
        "new": pkg_compare.remove_excluded_packages(
            filtered_new,
            exclude_list,
            exclude_patterns,
        ),
        "removed": pkg_compare.remove_excluded_packages(
            real_removals,
            exclude_list,
            exclude_patterns,
        ),
        "nv_updated": nv_updated,
        "nv_new": nv_new,
        "nv_removed": nv_removed,
    }


def _build_compare_parser(subparsers) -> argparse.ArgumentParser:
    """Create the compare subcommand parser."""
    parser = subparsers.add_parser(
        "compare",
        help="Compare two dpkg package lists and write the result lists.",
    )
    _add_compare_arguments(parser)
    return parser


def _build_download_parser(subparsers) -> argparse.ArgumentParser:
    """Create the download subcommand parser."""
    parser = subparsers.add_parser(
        "download",
        help="Download packages from a list using apt download.",
    )
    _add_download_arguments(parser)
    return parser


def _build_create_parser(subparsers) -> argparse.ArgumentParser:
    """Create the create subcommand parser."""
    parser = subparsers.add_parser(
        "create",
        help="Create an OTA-style SquashFS archive.",
    )
    _add_create_arguments(parser)
    return parser


def build_arg_parser() -> argparse.ArgumentParser:
    """Create the top-level ``ota-build`` parser."""
    parser = argparse.ArgumentParser(
        prog="ota-build",
        description="Unified OTA workflow controller for NUTS.",
        epilog=(
            "Examples:\n"
            "  ota-build compare old.list new.list --output-dir compare-out\n"
            "  ota-build download packages.txt --output-dir downloads\n"
            "  sudo ota-build create /path/to/staging --output ota.squashfs"
        ),
        formatter_class=argparse.RawTextHelpFormatter,
    )
    parser.add_argument(
        "-v",
        "--version",
        action="store_true",
        help="Show the version.",
    )
    subparsers = parser.add_subparsers(dest="command")
    _build_compare_parser(subparsers)
    _build_download_parser(subparsers)
    _build_create_parser(subparsers)
    return parser

def _run_compare(args) -> dict[str, list[str]]:
    """Run the compare workflow and emit the requested outputs."""
    output_dir = Path(args.output_dir).expanduser().resolve()
    tag = _compare_baseline_tag(args)
    nvidia_enabled = "nvopen" in tag.lower() or any(
        option is not None
        for option in (args.nv_new, args.nv_update, args.nv_remove)
    )
    output_names = _compare_output_names(
        tag,
        override_updated=args.out_updated,
        override_new=args.out_new,
        override_removed=args.out_removed,
        override_nv_new=args.nv_new,
        override_nv_update=args.nv_update,
        override_nv_remove=args.nv_remove,
        nvidia_enabled=nvidia_enabled,
    )
    updated_path = output_dir / output_names["updated"]
    new_path = output_dir / output_names["new"]
    removed_path = output_dir / output_names["removed"]
    nv_updated_path = output_names["nv_updated"] and (output_dir / output_names["nv_updated"])
    nv_new_path = output_names["nv_new"] and (output_dir / output_names["nv_new"])
    nv_removed_path = output_names["nv_removed"] and (output_dir / output_names["nv_removed"])

    announce_stage("Compare")
    plan_lines = [
        ("Baseline", tag),
        ("List A", args.list_a),
        ("List B", args.list_b),
        ("Output dir", str(output_dir)),
        ("Outputs", f"{updated_path.name}, {new_path.name}, {removed_path.name}"),
    ]
    if nvidia_enabled:
        plan_lines.append(
            ("NV outputs", f"{nv_updated_path.name}, {nv_new_path.name}, {nv_removed_path.name}")
        )
    else:
        plan_lines.append(("NV outputs", "disabled for this baseline"))
    render_summary("Compare Plan", plan_lines)

    state = _compare_state(args, nvidia_enabled=nvidia_enabled)
    render_summary(
        "Compare Summary",
        [
            ("Updated", len(state["updated"])),
            ("New", len(state["new"])),
            ("Removed", len(state["removed"])),
            ("NVIDIA updated", len(state["nv_updated"])),
            ("NVIDIA new", len(state["nv_new"])),
            ("NVIDIA removed", len(state["nv_removed"])),
        ],
    )

    output_dir.mkdir(parents=True, exist_ok=True)

    if nvidia_enabled:
        pkg_compare.save_packages_to_file(state["nv_updated"], str(nv_updated_path))
        pkg_compare.save_packages_to_file(state["nv_new"], str(nv_new_path))
        pkg_compare.save_packages_to_file(state["nv_removed"], str(nv_removed_path))
    pkg_compare.save_packages_to_file(state["updated"], str(updated_path))
    pkg_compare.save_packages_to_file(state["new"], str(new_path))
    pkg_compare.save_packages_to_file(state["removed"], str(removed_path))

    return state

def _run_download(args) -> None:
    """Run the download workflow."""
    announce_stage("Download")
    pkg_download.download_packages(args.file, args.output_dir)


def _run_create(args) -> None:
    """Run the archive creation workflow."""
    announce_stage("Archive")
    archive.create_archive(args.items, args.output)


def main(argv=None):
    """CLI entry point for the unified OTA workflow controller."""
    parser = build_arg_parser()
    args = parser.parse_args(argv)

    if args.version:
        print("ota-tooling 0.1.0")
        return

    if args.command is None:
        parser.print_help()
        raise SystemExit(1)

    if args.command == "compare":
        _run_compare(args)
    elif args.command == "download":
        _run_download(args)
    elif args.command == "create":
        _run_create(args)
    else:
        parser.print_help()
        raise SystemExit(1)
