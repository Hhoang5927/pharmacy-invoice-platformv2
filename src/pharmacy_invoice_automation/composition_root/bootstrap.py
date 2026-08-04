"""
bootstrap(): wires every concrete Infrastructure adapter (via
infrastructure.di.registration.register_infrastructure_services) into a
ServiceContainer. main(): the real CLI entry point (also what the
'pharmacy-invoice-automation' console script in pyproject.toml points
at) -- parses arguments and dispatches to composition_root.cli's
command implementations.

Growing incrementally, one Composition Root stage at a time (PO-
confirmed 2026-08): Stage A wired Infrastructure (registration.py);
Stage B added the 'scan' command (folder -> OCR -> validate, printed to
the terminal); Stage C added 'review' (minimal interactive review of
every UNDER_REVIEW invoice); Stage D adds 'automate' (drives the real
website for every READY_FOR_IMPORT invoice, with a --dry-run preview
mode and a mandatory typed confirmation before any real write) -- each
its own subcommand calling into composition_root.cli. A future
PySide6 Presentation layer would replace/supplement this CLI without
anything below composition_root changing -- both would drive the exact
same Application use cases.
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

from pharmacy_invoice_automation.composition_root import cli
from pharmacy_invoice_automation.infrastructure.di.registration import (
    register_infrastructure_services,
)
from pharmacy_invoice_automation.infrastructure.di.service_container import ServiceContainer


def _default_app_root() -> Path:
    """
    The application's base directory for data/logs/config (Technical
    Design Document Section 10): this project currently only runs from
    the repository itself (scripts/run_app.py's own framing), so this
    walks up from this file to the directory containing pyproject.toml
    -- the same repo-root-discovery pattern already used throughout
    this project's own test suite.
    """
    current = Path(__file__).resolve()
    for candidate in current.parents:
        if (candidate / "pyproject.toml").is_file():
            return candidate
    raise RuntimeError(
        "Could not locate the application root (no pyproject.toml found in any "
        f"parent of {current})."
    )


def bootstrap(app_root: Path | None = None) -> ServiceContainer:
    """Wire every real Infrastructure adapter into a fresh ServiceContainer."""
    container = ServiceContainer()
    register_infrastructure_services(container, app_root or _default_app_root())
    return container


def main() -> None:
    """CLI entry point: parse arguments and dispatch to a composition_root.cli command."""
    parser = argparse.ArgumentParser(
        prog="pharmacy-invoice-automation",
        description="Pharmacy purchase-invoice automation: OCR, review, and website entry.",
    )
    subparsers = parser.add_subparsers(dest="command", required=True)

    scan_parser = subparsers.add_parser(
        "scan",
        help="Scan a folder of invoice images, run OCR + validation, print results.",
    )
    scan_parser.add_argument(
        "image_folder", type=Path, help="Folder containing invoice images (png/jpg/jpeg/pdf)."
    )
    scan_parser.add_argument(
        "--project-name",
        default=None,
        help="Name for the new project (defaults to the folder name).",
    )

    subparsers.add_parser(
        "review",
        help="Interactively review every invoice currently UNDER_REVIEW.",
    )

    automate_parser = subparsers.add_parser(
        "automate",
        help=(
            "Drive the real webnhathuoc.com website to enter every "
            "READY_FOR_IMPORT invoice. Writes real data unless --dry-run "
            "is given."
        ),
    )
    automate_parser.add_argument(
        "--dry-run",
        action="store_true",
        help=(
            "Fill every field for real but stop before clicking 'Ghi "
            "Phieu' -- nothing is saved. Use this before ever running "
            "for real."
        ),
    )
    automate_parser.add_argument(
        "--headless",
        action="store_true",
        help=(
            "Run the browser headless (no visible window). Off by "
            "default so the operator can watch the automation happen, "
            "which matters most on a first real/dry run."
        ),
    )

    args = parser.parse_args()

    if args.command == "scan":
        image_folder: Path = args.image_folder
        if not image_folder.is_dir():
            print(f"'{image_folder}' is not a folder.", file=sys.stderr)
            raise SystemExit(1)
        project_name = args.project_name or image_folder.name
        container = bootstrap()
        cli.run_scan(container, image_folder, project_name)
    elif args.command == "review":
        container = bootstrap()
        cli.run_review(container)
    elif args.command == "automate":
        container = bootstrap()
        cli.run_automate(container, dry_run=args.dry_run, headless=args.headless)


if __name__ == "__main__":
    main()
