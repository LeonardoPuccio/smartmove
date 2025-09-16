"""
File Mover

Main orchestrator for file moving operations.
"""

import logging
import shutil
from datetime import datetime
from pathlib import Path

from directory_manager import DirectoryManager

from cross_filesystem import CrossFilesystemMover

logger = logging.getLogger(__name__)


class FileMover:
    """Main orchestrator for file moving operations"""

    def __init__(
        self,
        source_path,
        dest_path,
        create_parents=False,
        dry_run=False,
        quiet=False,
        comprehensive_scan=False,
    ):
        self.source_path = Path(source_path)
        self.dest_path = Path(dest_path)

        # Handle directory destinations
        if str(dest_path).endswith("/") or (
            self.dest_path.exists() and self.dest_path.is_dir()
        ):
            # If destination is a directory, append source filename
            self.dest_path = self.dest_path / self.source_path.name

        self.create_parents = create_parents
        self.dry_run = dry_run
        self.quiet = quiet
        self.dir_manager = DirectoryManager(dry_run)
        self.comprehensive_scan = comprehensive_scan

        if not self.source_path.exists():
            raise ValueError(f"Source does not exist: {source_path}")

        if not self.dest_path.parent.exists() and not create_parents:
            raise ValueError(
                f"Destination parent directory does not exist: {self.dest_path.parent}\n"
                f"Use -p to create parent directories"
            )

    def _print_action(self, message):
        """Print action with timestamp unless quiet mode"""
        if not self.quiet:
            timestamp = datetime.now().strftime("%Y-%m-%d %H:%M:%S,%f")[:-3]
            print(f"{timestamp} - {message}")

    def _detect_same_filesystem(self):
        """Check if source and destination are on same filesystem"""
        try:
            source_dev = self.source_path.stat().st_dev

            dest_check = self.dest_path.parent
            while not dest_check.exists() and dest_check.parent != dest_check:
                dest_check = dest_check.parent

            dest_dev = dest_check.stat().st_dev
            logger.debug(f"Source dev: {source_dev}, Dest dev: {dest_dev}")

            return source_dev == dest_dev

        except OSError as e:
            logger.debug(f"Could not detect filesystem devices: {e}")
            return False

    def _simple_move(self):
        """Simple same-filesystem move preserving hardlinks automatically"""
        try:
            if not self.dry_run:
                shutil.move(str(self.source_path), str(self.dest_path))
            action = "Would move" if self.dry_run else "✓ Moved"
            self._print_action(f"{action}: {self.source_path} → {self.dest_path}")
            return True
        except Exception as e:
            logger.error(f"Move failed: {self.source_path} → {self.dest_path}: {e}")
            return False

    def move(self):
        """Execute the move operation"""
        if self.dry_run:
            timestamp = datetime.now().strftime("%Y-%m-%d %H:%M:%S,%f")[:-3]
            print(f"{timestamp} - DRY RUN - Previewing actions only")

        # Create parent directory if needed
        if self.create_parents and not self.dest_path.parent.exists():
            self.dir_manager.ensure_directory(self.dest_path.parent)
            if not self.dry_run:
                action = "✓ Created parent directory"
            else:
                action = "Would create parent directory"
            self._print_action(f"{action}: {self.dest_path.parent}")

        if self._detect_same_filesystem():
            logger.debug("Using simple move for same filesystem")
            success = self._simple_move()
        else:
            logger.info("Cross-filesystem operation detected")
            cross_mover = CrossFilesystemMover(
                self.source_path,
                self.dest_path,
                self.dry_run,
                self.quiet,
                self.dir_manager,
                self.comprehensive_scan,
            )

            if self.source_path.is_file():
                success = cross_mover.move_file()
            elif self.source_path.is_dir():
                success = cross_mover.move_directory()
            else:
                logger.error(f"Unsupported source type: {self.source_path}")
                return False

        if success:
            action = (
                "Would complete operation"
                if self.dry_run
                else "Operation completed successfully"
            )
            self._print_action(action)

        return success
