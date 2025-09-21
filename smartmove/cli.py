#!/usr/bin/env python3
"""
Cross-Filesystem File Mover with Hardlink Preservation

Moves files/directories between filesystems while preserving hardlink relationships.
Uses mv-like interface with automatic cross-filesystem detection.

Usage:
    sudo python3 smartmove.py SOURCE DEST [options]
    sudo python3 smartmove.py "/mnt/ssd/movie" "/mnt/hdd/movie" --dry-run
    sudo python3 smartmove.py "/mnt/ssd/movie" "/mnt/hdd/movie" -p --comprehensive
"""

import argparse
import logging
import os
import sys

from smartmove.core import FileMover

# Configure logging
logging.basicConfig(
    level=logging.WARNING, format="%(asctime)s - %(levelname)s - %(message)s"
)
logger = logging.getLogger(__name__)


def main():
    parser = argparse.ArgumentParser(
        description="Cross-filesystem file mover with hardlink preservation",
        epilog="Example: smartmove.py '/mnt/ssd/movie' '/mnt/hdd/movie' --dry-run",
    )
    parser.add_argument("source", help="Source file or directory path")
    parser.add_argument("dest", help="Destination file or directory path")
    parser.add_argument(
        "-p",
        "--parents",
        action="store_true",
        help="Create parent directories as needed",
    )
    parser.add_argument(
        "--dry-run", action="store_true", help="Preview actions without executing moves"
    )
    parser.add_argument(
        "--comprehensive",
        action="store_true",
        help="Scan all mounted filesystems for hardlinks (slower, for complex storage setups)",
    )
    parser.add_argument(
        "-v",
        "--verbose",
        action="store_true",
        help="Enable verbose logging (show process information)",
    )
    parser.add_argument(
        "--debug", action="store_true", help="Enable debug logging (requires --verbose)"
    )
    parser.add_argument(
        "-q", "--quiet", action="store_true", help="Suppress output except errors"
    )
    parser.add_argument(
        "--no-progress", action="store_true", help="Disable progress display"
    )
    parser.add_argument("--version", action="version", version="SmartMove 0.2.0")

    args = parser.parse_args()

    # Set logging levels
    if args.debug:
        if not args.verbose:
            parser.error("--debug requires --verbose")
        logging.getLogger().setLevel(logging.DEBUG)
    elif args.verbose:
        logging.getLogger().setLevel(logging.INFO)
    else:
        logging.getLogger().setLevel(logging.ERROR)

    if os.geteuid() != 0:
        logger.error("Root privileges required for file ownership preservation")
        sys.exit(1)

    try:
        mover = FileMover(
            args.source,
            args.dest,
            args.parents,
            args.dry_run,
            args.quiet,
            args.comprehensive,
            show_progress=not args.no_progress,
        )
        success = mover.move()

        if not success:
            logger.error("Operation failed")
            sys.exit(1)

    except Exception as e:
        logger.error(f"Fatal error: {e}")
        sys.exit(1)


if __name__ == "__main__":
    main()
