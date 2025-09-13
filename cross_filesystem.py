"""
Cross-Filesystem Mover

Handles cross-filesystem moves with hardlink preservation.
"""

import logging
import os
import shutil
import signal
import subprocess
import sys
import time
from datetime import datetime
from pathlib import Path

logger = logging.getLogger(__name__)


class CrossFilesystemMover:
    """Handles cross-filesystem moves with hardlink preservation"""

    def __init__(
        self,
        source_path,
        dest_path,
        dry_run=False,
        quiet=False,
        dir_manager=None,
        comprehensive_scan=False,
    ):
        self.source_path = source_path
        self.dest_path = dest_path
        self.dry_run = dry_run
        self.quiet = quiet
        self.dir_manager = dir_manager
        self.comprehensive_scan = comprehensive_scan
        self.moved_inodes = set()
        self.inode_link_counts = {}

        # Edge case handling: temp file tracking
        self.temp_files = set()

        # Cache both mount points once
        self.source_root = self._find_mount_point(self.source_path)
        self.dest_root = self._find_mount_point(self.dest_path)
        self.hardlink_index = None

        # Register signal handlers for cleanup
        self._register_cleanup_handlers()

        # Validate before starting
        self._validate_permissions()
        self._validate_space()

        scan_type = "comprehensive" if comprehensive_scan else "source-filesystem-only"
        logger.debug(
            f"Source mount point: {self.source_root}, Dest mount point: {self.dest_root}, scan mode: {scan_type}"
        )

    def _register_cleanup_handlers(self):
        """Register signal handlers for graceful cleanup"""

        def cleanup_handler(signum, frame):
            logger.info(f"Received signal {signum}, cleaning up...")
            self._cleanup_temp_files()
            sys.exit(1)

        signal.signal(signal.SIGINT, cleanup_handler)
        signal.signal(signal.SIGTERM, cleanup_handler)

    def _cleanup_temp_files(self):
        """Clean up any temporary files"""
        for temp_file in self.temp_files:
            try:
                if temp_file.exists():
                    temp_file.unlink()
                    logger.debug(f"Cleaned up temp file: {temp_file}")
            except Exception as e:
                logger.debug(f"Failed to cleanup {temp_file}: {e}")
        self.temp_files.clear()

    def _track_temp_file(self, temp_file):
        """Track temporary file for cleanup"""
        self.temp_files.add(temp_file)

    def _untrack_temp_file(self, temp_file):
        """Remove file from temp tracking"""
        self.temp_files.discard(temp_file)

    def _validate_permissions(self):
        """Check read/write permissions before operation"""
        if not os.access(self.source_path, os.R_OK):
            raise PermissionError(f"Cannot read source: {self.source_path}")

        dest_check = self.dest_path.parent
        while not dest_check.exists() and dest_check.parent != dest_check:
            dest_check = dest_check.parent

        if not os.access(dest_check, os.W_OK):
            raise PermissionError(f"Cannot write to destination: {dest_check}")

    def _validate_space(self):
        """Check available disk space using cached destination mount point"""
        if self.source_path.is_file():
            source_size = self.source_path.stat().st_size
        else:
            try:
                source_size = sum(
                    f.stat().st_size for f in self.source_path.rglob("*") if f.is_file()
                )
            except OSError as e:
                raise RuntimeError(
                    f"Cannot calculate source size for space validation: {e}"
                )

        try:
            dest_free = shutil.disk_usage(self.dest_root).free
            if source_size > dest_free * 0.9:  # 10% buffer
                raise ValueError(
                    f"Insufficient space: need {source_size:,} bytes, have {dest_free:,} available"
                )
        except OSError as e:
            raise RuntimeError(f"Cannot check destination space: {e}")

    def _print_action(self, message):
        """Print action with timestamp unless quiet mode"""
        if not self.quiet:
            timestamp = datetime.now().strftime("%Y-%m-%d %H:%M:%S,%f")[:-3]
            print(f"{timestamp} - {message}")

    def _find_mount_point(self, path):
        """Find mount point for given path, handling non-existent paths"""
        path = Path(path)

        # Walk up to find existing directory first
        while not path.exists() and path.parent != path:
            path = path.parent

        # Now find mount point from existing path
        path = os.path.realpath(str(path))
        while not os.path.ismount(path):
            parent = os.path.dirname(path)
            if parent == path:
                break
            path = parent
        return Path(path)

    def _build_hardlink_index(self):
        """Build memory index of hardlinks using find command"""
        if self.hardlink_index is not None:
            return

        scan_scope = (
            "all mounted filesystems"
            if self.comprehensive_scan
            else f"filesystem {self.source_root}"
        )
        logger.debug(f"Building hardlink index for {scan_scope}")
        self.hardlink_index = {}

        try:
            # Choose command based on comprehensive_scan flag
            if self.comprehensive_scan:
                # Scan all mounted filesystems (slower but comprehensive)
                cmd = [
                    "find",
                    str(self.source_root),
                    "-type",
                    "f",
                    "-links",
                    "+1",
                    "-printf",
                    "%i %p\n",
                ]
                logger.info(
                    "Using comprehensive scan - may take longer but finds hardlinks across all filesystems"
                )
            else:
                # Default: scan only source filesystem (faster)
                cmd = [
                    "find",
                    str(self.source_root),
                    "-xdev",
                    "-type",
                    "f",
                    "-links",
                    "+1",
                    "-printf",
                    "%i %p\n",
                ]
                logger.debug(
                    "Using source-filesystem-only scan for optimal performance"
                )

            result = subprocess.run(
                cmd, capture_output=True, text=True, timeout=300, check=True
            )

            for line in result.stdout.strip().split("\n"):
                if not line.strip():
                    continue

                parts = line.strip().split(" ", 1)
                if len(parts) == 2:
                    try:
                        inode = int(parts[0])
                        file_path = Path(parts[1])

                        if inode not in self.hardlink_index:
                            self.hardlink_index[inode] = []
                        self.hardlink_index[inode].append(file_path)
                    except (ValueError, OSError):
                        continue

            hardlink_groups = len(self.hardlink_index)
            total_hardlinked_files = sum(
                len(paths) for paths in self.hardlink_index.values()
            )
            scope_desc = (
                "across all filesystems"
                if self.comprehensive_scan
                else "within source filesystem only"
            )
            logger.debug(
                f"Indexed {hardlink_groups} hardlink groups ({total_hardlinked_files} files) {scope_desc}"
            )

        except (subprocess.CalledProcessError, subprocess.TimeoutExpired, OSError) as e:
            scan_type = (
                "comprehensive" if self.comprehensive_scan else "source-filesystem-only"
            )
            raise RuntimeError(
                f"Hardlink detection failed ({scan_type} scan) - tool cannot preserve hardlinks: {e}"
            )

    def find_hardlinks(self, file_path):
        """Find all hardlinks for file using memory index"""
        try:
            file_stat = file_path.stat()

            # Build index only when hardlinks detected
            if file_stat.st_nlink <= 1:
                return [file_path]

            if self.hardlink_index is None:
                self._build_hardlink_index()

            inode = file_stat.st_ino
            hardlinks = self.hardlink_index.get(inode, [file_path])

            if len(hardlinks) > 1:
                logger.debug(f"Found {len(hardlinks)} hardlinks for inode {inode}")

            return hardlinks

        except OSError as e:
            logger.debug(f"Hardlink detection failed for {file_path}: {e}")
            return [file_path]

    def map_hardlink_destination(self, source_hardlink):
        """Map hardlink destination path, handling cross-scope hardlinks"""
        try:
            # Standard case: hardlink within source directory
            rel_path = source_hardlink.relative_to(self.source_path)
            return self.dest_path / rel_path
        except ValueError:
            # Cross-scope: preserve original directory structure
            source_relative = source_hardlink.relative_to(self.source_root)
            return self.dest_root / source_relative

    def create_file(self, source_file, dest_file, final_path=None):
        """Create file at destination via copy with retry logic"""
        try:
            self.dir_manager.ensure_directory(dest_file.parent)

            if not self.dry_run:
                # Retry logic for permission errors
                max_retries = 2
                for attempt in range(max_retries):
                    try:
                        shutil.copy2(source_file, dest_file)
                        break
                    except PermissionError as e:
                        if attempt < max_retries - 1:
                            logger.debug(
                                f"Permission error on attempt {attempt + 1}, retrying: {e}"
                            )
                            time.sleep(0.1)  # Brief delay
                        else:
                            raise
                    except OSError as e:
                        if e.errno == 28:  # No space left
                            logger.error(f"Disk space exhausted: {e}")
                            return False
                        raise

                # Preserve ownership and permissions
                source_stat = source_file.stat()
                os.chmod(dest_file, source_stat.st_mode)
                try:
                    os.chown(dest_file, source_stat.st_uid, source_stat.st_gid)
                except PermissionError:
                    logger.debug(f"Could not preserve ownership for {dest_file}")

            # Log final path, not temp path
            display_path = final_path if final_path else dest_file
            action = "Would create" if self.dry_run else "✓ Created"
            self._print_action(f"{action}: {display_path}")
            return True

        except Exception as e:
            logger.error(f"Copy failed: {source_file} → {dest_file}: {e}")
            return False

    def create_hardlink(
        self, primary_dest_file, dest_hardlink, source_file, final_path=None
    ):
        """Create hardlink to existing destination file with retry logic"""
        try:
            self.dir_manager.ensure_directory(dest_hardlink.parent)

            if not self.dry_run:
                # Retry logic for permission errors
                max_retries = 2
                for attempt in range(max_retries):
                    try:
                        os.link(primary_dest_file, dest_hardlink)
                        break
                    except PermissionError as e:
                        if attempt < max_retries - 1:
                            logger.debug(
                                f"Permission error on hardlink attempt {attempt + 1}, retrying: {e}"
                            )
                            time.sleep(0.1)
                        else:
                            # Fall back to copy
                            logger.debug(f"Hardlink failed, falling back to copy: {e}")
                            return self.create_file(
                                source_file, dest_hardlink, final_path
                            )
                    except OSError as e:
                        if e.errno == 18:  # Cross-device fallback
                            logger.debug(
                                f"Cross-device hardlink failed, copying {dest_hardlink.name}"
                            )
                            return self.create_file(
                                source_file, dest_hardlink, final_path
                            )
                        else:
                            logger.error(
                                f"Hardlink creation failed: {dest_hardlink}: {e}"
                            )
                            return False

            # Log final path, not temp path
            display_path = final_path if final_path else dest_hardlink
            action = "Would link" if self.dry_run else "✓ Linked"
            self._print_action(f"{action}: {display_path}")
            return True

        except Exception as e:
            logger.error(f"Hardlink creation failed: {dest_hardlink}: {e}")
            return False

    def move_hardlink_group(self, source_file, dest_file):
        """Move file and recreate hardlinks atomically with temp file tracking"""
        file_stat = source_file.stat()

        if file_stat.st_ino in self.moved_inodes:
            logger.debug(f"Skipping already processed inode {file_stat.st_ino}")
            return True

        self.inode_link_counts[file_stat.st_ino] = file_stat.st_nlink

        message = "Processing" if not self.dry_run else "Would process"
        logger.debug(f"{message}: {source_file}")
        hardlinks = self.find_hardlinks(source_file)

        if len(hardlinks) > 1:
            # Create all files with temp names first
            temp_suffix = f".smartmove_{os.getpid()}"
            temp_files = []

            try:
                # Create primary file
                temp_dest = dest_file.with_suffix(dest_file.suffix + temp_suffix)
                if not self.dry_run:
                    self._track_temp_file(temp_dest)

                if not self.create_file(source_file, temp_dest, dest_file):
                    return False
                temp_files.append((temp_dest, dest_file))

                # Create hardlinks for other instances
                for hardlink in hardlinks:
                    if hardlink != source_file:
                        dest_hardlink = self.map_hardlink_destination(hardlink)
                        temp_hardlink = dest_hardlink.with_suffix(
                            dest_hardlink.suffix + temp_suffix
                        )

                        if not self.dry_run:
                            self._track_temp_file(temp_hardlink)

                        if self.create_hardlink(
                            temp_dest, temp_hardlink, hardlink, dest_hardlink
                        ):
                            temp_files.append((temp_hardlink, dest_hardlink))
                        else:
                            raise RuntimeError(
                                f"Failed to create hardlink: {temp_hardlink}"
                            )

                # Atomic rename all files
                if not self.dry_run:
                    for temp_file, final_file in temp_files:
                        temp_file.rename(final_file)
                        self._untrack_temp_file(temp_file)

                # Remove sources after successful destination creation
                for link in hardlinks:
                    if not self.dry_run:
                        link.unlink()
                    self._print_action(
                        f"Would remove: {link}"
                        if self.dry_run
                        else f"✓ Removed: {link}"
                    )

                self.moved_inodes.add(file_stat.st_ino)
                return True

            except Exception as e:
                # Cleanup temp files on failure
                if not self.dry_run:
                    for temp_file, _ in temp_files:
                        try:
                            if temp_file.exists():
                                temp_file.unlink()
                            self._untrack_temp_file(temp_file)
                        except FileNotFoundError:
                            pass
                logger.error(f"Atomic operation failed: {e}")
                return False

        else:
            # Single file case
            if self.create_file(source_file, dest_file):
                if not self.dry_run:
                    source_file.unlink()
                action = "Would remove" if self.dry_run else "✓ Removed"
                self._print_action(f"{action}: {source_file}")
                self.moved_inodes.add(file_stat.st_ino)
                return True

        return False

    def move_file(self):
        """Move single file with hardlink preservation"""
        return self.move_hardlink_group(self.source_path, self.dest_path)

    def move_directory(self):
        """Move directory structure with hardlink preservation"""
        scan_mode = "comprehensive" if self.comprehensive_scan else "optimized"
        logger.info(
            f"Moving directory ({scan_mode} scan): {self.source_path} → {self.dest_path}"
        )

        files_processed = 0
        for root, dirs, files in os.walk(self.source_path):
            for file_name in files:
                source_file = Path(root) / file_name

                # Skip if file already processed (removed as part of hardlink group)
                if not source_file.exists():
                    continue

                rel_path = source_file.relative_to(self.source_path)
                dest_file = self.dest_path / rel_path

                if self.move_hardlink_group(source_file, dest_file):
                    files_processed += 1

        # Clean up empty directories
        if not self.dry_run:
            self._remove_empty_dirs()

        # Count only actual hardlink groups (original link count > 1)
        hardlink_groups = sum(
            1 for inode, count in self.inode_link_counts.items() if count > 1
        )
        message = "Directory completed" if not self.dry_run else "Preview completed"
        if hardlink_groups > 0:
            logger.info(
                f"{message}: {files_processed} files, {hardlink_groups} hardlink groups preserved"
            )
        else:
            logger.info(f"{message}: {files_processed} files processed")
        return True

    def _remove_empty_dirs(self):
        """Remove empty directories bottom-up"""
        try:
            for root, dirs, files in os.walk(self.source_path, topdown=False):
                root_path = Path(root)
                if root_path.exists() and not any(root_path.iterdir()):
                    root_path.rmdir()
                    action = (
                        "Would remove empty directory"
                        if self.dry_run
                        else "✓ Removed empty directory"
                    )
                    self._print_action(f"{action}: {root_path}")
        except OSError as e:
            logger.debug(f"Directory cleanup issue: {e}")
