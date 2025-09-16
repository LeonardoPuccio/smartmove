#!/usr/bin/env python3
"""
Unit tests for SmartMove components
Updated with new optimizations (mount point detection, memory index)
"""

import os
import shutil
import subprocess
import tempfile
import unittest
from pathlib import Path
from unittest.mock import MagicMock, patch

from smartmove.core import CrossFilesystemMover, FileMover
from smartmove.utils import DirectoryManager


class TestDirectoryManager(unittest.TestCase):
    def setUp(self):
        self.temp_dir = Path(tempfile.mkdtemp())
        self.addCleanup(shutil.rmtree, self.temp_dir, ignore_errors=True)
        self.dir_manager = DirectoryManager(dry_run=False)

    def test_ensure_directory_creates_path(self):
        """Test that ensure_directory creates nested directory structure"""
        test_path = self.temp_dir / "new" / "nested" / "path"
        self.dir_manager.ensure_directory(test_path)

        self.assertTrue(test_path.exists(), "Directory should be created")
        self.assertTrue(test_path.is_dir(), "Created path should be a directory")

    def test_ensure_directory_caching(self):
        """Test that directory creation is cached to avoid redundant operations"""
        test_path = self.temp_dir / "cached"

        # First call should create
        self.dir_manager.ensure_directory(test_path)
        self.assertIn(
            test_path,
            self.dir_manager.created_dirs,
            "Path should be cached after creation",
        )

        # Second call should use cache
        with patch("pathlib.Path.mkdir") as mock_mkdir:
            self.dir_manager.ensure_directory(test_path)
            mock_mkdir.assert_not_called()

    def test_dry_run_mode(self):
        """Test that dry-run mode prevents actual directory creation"""
        dry_manager = DirectoryManager(dry_run=True)
        test_path = self.temp_dir / "dry_run_test"

        dry_manager.ensure_directory(test_path)
        self.assertFalse(
            test_path.exists(), "Directory should not be created in dry-run mode"
        )
        self.assertIn(
            test_path,
            dry_manager.created_dirs,
            "Path should still be cached in dry-run mode",
        )


class TestCrossFilesystemMover(unittest.TestCase):
    def setUp(self):
        self.temp_dir = Path(tempfile.mkdtemp())
        self.addCleanup(shutil.rmtree, self.temp_dir, ignore_errors=True)
        self.source_dir = self.temp_dir / "source"
        self.dest_dir = self.temp_dir / "dest"
        self.source_dir.mkdir()
        self.dest_dir.mkdir()

        self.dir_manager = DirectoryManager(dry_run=True)
        self.mover = CrossFilesystemMover(
            self.source_dir,
            self.dest_dir,
            dry_run=True,
            quiet=True,
            dir_manager=self.dir_manager,
        )

    def test_mount_point_detection(self):
        """Test mount point detection using os.path.ismount"""
        # Test with mock mount point
        with patch("os.path.ismount") as mock_ismount:
            # Simulate mount point at /mnt/test
            def ismount_side_effect(path):
                return str(path) == "/mnt/test"

            mock_ismount.side_effect = ismount_side_effect

            with patch(
                "os.path.realpath", return_value="/mnt/test/deep/nested/file.txt"
            ):
                mount_point = self.mover._find_mount_point(
                    Path("/mnt/test/deep/nested/file.txt")
                )
                self.assertEqual(mount_point, Path("/mnt/test"))

    def test_mount_point_detection_root_fallback(self):
        """Test mount point detection falls back to root"""
        with patch("os.path.ismount", return_value=False):
            with patch("os.path.realpath", return_value="/some/path"):
                mount_point = self.mover._find_mount_point(Path("/some/path"))
                self.assertEqual(mount_point, Path("/"))

    def test_hardlink_index_building(self):
        """Test memory index building for hardlinks"""
        # Mock subprocess.run to simulate find command output
        mock_output = "12345 /path/to/file1.txt\n12345 /path/to/file2.txt\n67890 /path/to/file3.txt\n"

        with patch("subprocess.run") as mock_run:
            mock_run.return_value.returncode = 0
            mock_run.return_value.stdout = mock_output

            self.mover._build_hardlink_index()

            # Verify index was built correctly
            self.assertIsNotNone(self.mover.hardlink_index)
            self.assertIn(12345, self.mover.hardlink_index)
            self.assertIn(67890, self.mover.hardlink_index)
            self.assertEqual(len(self.mover.hardlink_index[12345]), 2)
            self.assertEqual(len(self.mover.hardlink_index[67890]), 1)

    def test_hardlink_index_error_handling(self):
        """Test hardlink index handles errors gracefully"""
        with patch("subprocess.run") as mock_run:
            mock_run.return_value.returncode = 1
            mock_run.return_value.stderr = "Permission denied"

            self.mover._build_hardlink_index()

            # Should create empty index on error
            self.assertEqual(self.mover.hardlink_index, {})

    def test_find_hardlinks_single_file(self):
        """Test hardlink detection for files without hardlinks"""
        single_file = self.source_dir / "single.txt"
        single_file.write_text("single file")

        hardlinks = self.mover.find_hardlinks(single_file)

        self.assertEqual(len(hardlinks), 1, "Single file should return only itself")
        self.assertEqual(
            hardlinks[0], single_file, "Returned file should be the original"
        )

    def test_find_hardlinks_with_index(self):
        """Test hardlink detection using memory index"""
        test_file = self.source_dir / "test.txt"
        test_file.write_text("test content")

        # Mock os.stat instead of Path.stat
        with patch("os.stat") as mock_stat:
            # Create mock stat result
            mock_stat_result = type("MockStat", (), {"st_nlink": 3, "st_ino": 12345})()
            mock_stat.return_value = mock_stat_result

            # Pre-populate index
            self.mover.hardlink_index = {
                12345: [
                    Path("/path/to/file1.txt"),
                    Path("/path/to/file2.txt"),
                    Path("/path/to/file3.txt"),
                ]
            }

            hardlinks = self.mover.find_hardlinks(test_file)

            self.assertEqual(
                len(hardlinks), 3, "Should return all hardlinks from index"
            )

    def test_find_hardlinks_builds_index_on_demand(self):
        """Test that index is built when first needed"""
        test_file = self.source_dir / "test.txt"
        test_file.write_text("test content")

        # Ensure index starts as None
        self.mover.hardlink_index = None

        # Mock os.stat to simulate multiple links
        with patch("os.stat") as mock_stat:
            mock_stat_result = type("MockStat", (), {"st_nlink": 2, "st_ino": 12345})()
            mock_stat.return_value = mock_stat_result

            # Mock _build_hardlink_index to set up empty index
            def mock_build_index():
                self.mover.hardlink_index = {}

            with patch.object(
                self.mover, "_build_hardlink_index", side_effect=mock_build_index
            ) as mock_build:
                hardlinks = self.mover.find_hardlinks(test_file)
                mock_build.assert_called_once()
                # Should return the test file since index is empty
                self.assertEqual(len(hardlinks), 1)
                self.assertEqual(hardlinks[0], test_file)

    def test_map_hardlink_destination_within_scope(self):
        """Test hardlink destination mapping for files within move scope"""
        source_file = self.source_dir / "subdir" / "file.txt"
        mapped_dest = self.mover.map_hardlink_destination(source_file)

        expected_dest = self.dest_dir / "subdir" / "file.txt"
        self.assertEqual(mapped_dest, expected_dest)

    def test_map_hardlink_destination_outside_scope(self):
        """Test hardlink destination mapping for files outside move scope"""
        outside_file = self.temp_dir / "outside" / "file.txt"
        mapped_dest = self.mover.map_hardlink_destination(outside_file)

        # Should preserve directory structure relative to filesystem root
        expected_dest = self.temp_dir / "outside" / "file.txt"
        self.assertEqual(mapped_dest, expected_dest)

    def test_create_file_preserves_stats(self):
        """Test that file creation preserves ownership and permissions"""
        source_file = self.source_dir / "test.txt"
        source_file.write_text("test content")
        dest_file = self.dest_dir / "copied.txt"

        # Test in non-dry-run mode
        real_mover = CrossFilesystemMover(
            self.source_dir,
            self.dest_dir,
            dry_run=False,
            quiet=True,
            dir_manager=DirectoryManager(dry_run=False),
        )

        with patch("shutil.copy2") as mock_copy:
            with patch("os.chmod") as mock_chmod:
                with patch("os.chown") as mock_chown:
                    success = real_mover.create_file(source_file, dest_file)

                    self.assertTrue(success)
                    mock_copy.assert_called_once_with(source_file, dest_file)
                    mock_chmod.assert_called_once()
                    mock_chown.assert_called_once()

    def test_create_hardlink_cross_device_fallback(self):
        """Test hardlink creation falls back to copy on cross-device error"""
        primary_file = self.dest_dir / "primary.txt"
        primary_file.write_text("content")
        dest_link = self.dest_dir / "hardlink.txt"
        source_file = self.source_dir / "source.txt"
        source_file.write_text("content")

        real_mover = CrossFilesystemMover(
            self.source_dir,
            self.dest_dir,
            dry_run=False,
            quiet=True,
            dir_manager=DirectoryManager(dry_run=False),
        )

        # Mock os.link to raise cross-device error
        with patch("os.link", side_effect=OSError(18, "Cross-device link")):
            with patch.object(
                real_mover, "create_file", return_value=True
            ) as mock_create:
                success = real_mover.create_hardlink(
                    primary_file, dest_link, source_file
                )

                self.assertTrue(success)
                mock_create.assert_called_once_with(source_file, dest_link, None)

    def test_create_hardlink_success(self):
        """Test successful hardlink creation"""
        primary_file = self.dest_dir / "primary.txt"
        primary_file.write_text("content")
        dest_link = self.dest_dir / "hardlink.txt"
        source_file = self.source_dir / "source.txt"
        source_file.write_text("content")

        real_mover = CrossFilesystemMover(
            self.source_dir,
            self.dest_dir,
            dry_run=False,
            quiet=True,
            dir_manager=DirectoryManager(dry_run=False),
        )

        success = real_mover.create_hardlink(primary_file, dest_link, source_file)

        self.assertTrue(success)
        self.assertTrue(dest_link.exists())
        self.assertEqual(primary_file.stat().st_ino, dest_link.stat().st_ino)

    def test_create_hardlink_non_cross_device_error(self):
        """Test hardlink creation with non-cross-device OSError"""
        primary_file = self.dest_dir / "primary.txt"
        primary_file.write_text("content")
        dest_link = self.dest_dir / "hardlink.txt"
        source_file = self.source_dir / "source.txt"
        source_file.write_text("content")

        real_mover = CrossFilesystemMover(
            self.source_dir,
            self.dest_dir,
            dry_run=False,
            quiet=True,
            dir_manager=DirectoryManager(dry_run=False),
        )

        # Mock os.link to raise non-cross-device error
        with patch("os.link", side_effect=OSError(13, "Permission denied")):
            success = real_mover.create_hardlink(primary_file, dest_link, source_file)

            self.assertTrue(success)

    def test_create_hardlink_final_path_logging(self):
        """Test that final path is logged correctly"""
        primary_file = self.dest_dir / "primary.txt"
        primary_file.write_text("content")
        dest_link = self.dest_dir / "temp.txt.smartmove_123"
        final_path = self.dest_dir / "final.txt"
        source_file = self.source_dir / "source.txt"
        source_file.write_text("content")

        real_mover = CrossFilesystemMover(
            self.source_dir,
            self.dest_dir,
            dry_run=False,
            quiet=False,
            dir_manager=DirectoryManager(dry_run=False),
        )

        with patch.object(real_mover, "_print_action") as mock_print:
            success = real_mover.create_hardlink(
                primary_file, dest_link, source_file, final_path
            )

            self.assertTrue(success)
            # Should log final_path, not dest_link
            mock_print.assert_called_once()
            call_args = mock_print.call_args[0][0]
            self.assertIn(str(final_path), call_args)
            self.assertNotIn("smartmove_123", call_args)

    def test_space_validation_calculation_failure(self):
        """Test space validation when source size calculation fails"""
        # Create mover that will fail during space calculation
        large_dir = self.source_dir / "large"
        large_dir.mkdir()

        with patch("pathlib.Path.rglob", side_effect=PermissionError("Access denied")):
            with self.assertRaises(RuntimeError) as context:
                CrossFilesystemMover(
                    self.source_dir,
                    self.dest_dir,
                    dry_run=False,
                    quiet=True,
                    dir_manager=DirectoryManager(),
                )

            self.assertIn("Cannot calculate source size", str(context.exception))

    def test_cross_scope_hardlink_mapping(self):
        """Test cross-scope hardlink destination mapping"""
        outside_file = self.temp_dir / "outside_scope.txt"

        mover = CrossFilesystemMover(
            self.source_dir,
            self.dest_dir,
            dry_run=True,
            quiet=True,
            dir_manager=DirectoryManager(),
        )

        mapped = mover.map_hardlink_destination(outside_file)
        expected = self.temp_dir / "outside_scope.txt"

        self.assertEqual(mapped, expected)

    def test_atomic_operation_partial_failure(self):
        """Test atomic operation cleanup on partial failure"""
        # Create test file with hardlinks
        test_file = self.source_dir / "test.txt"
        test_file.write_text("content")
        link_file = self.source_dir / "link.txt"
        os.link(test_file, link_file)

        real_mover = CrossFilesystemMover(
            self.source_dir,
            self.dest_dir,
            dry_run=False,
            quiet=True,
            dir_manager=DirectoryManager(dry_run=False),
        )

        # Mock find_hardlinks to return both files
        with patch.object(
            real_mover, "find_hardlinks", return_value=[test_file, link_file]
        ):
            # Mock create_hardlink to fail on second call
            with patch.object(real_mover, "create_hardlink", side_effect=[True, False]):
                with patch.object(real_mover, "create_file", return_value=True):
                    # Should fail and cleanup temp files
                    success = real_mover.move_hardlink_group(
                        test_file, self.dest_dir / "moved.txt"
                    )

                    self.assertFalse(success)
                    # Verify no temp files left behind
                    temp_files = list(self.dest_dir.glob("*.smartmove_*"))
                    self.assertEqual(len(temp_files), 0)

    def test_hardlink_detection_timeout(self):
        """Test hardlink detection timeout handling"""
        mover = CrossFilesystemMover(
            self.source_dir,
            self.dest_dir,
            dry_run=True,
            quiet=True,
            dir_manager=DirectoryManager(),
        )

        # Mock subprocess to timeout
        with patch(
            "subprocess.run", side_effect=subprocess.TimeoutExpired(["find"], 300)
        ):
            with self.assertRaises(RuntimeError) as context:
                mover._build_hardlink_index()

            self.assertIn("Hardlink detection failed", str(context.exception))

    def test_move_hardlink_group_skips_processed_inodes(self):
        """Test that already processed inodes are skipped"""
        test_file = self.source_dir / "test.txt"
        test_file.write_text("test content")
        dest_file = self.dest_dir / "moved.txt"

        # Mark inode as already processed
        test_inode = test_file.stat().st_ino
        self.mover.moved_inodes.add(test_inode)

        success = self.mover.move_hardlink_group(test_file, dest_file)

        self.assertTrue(success, "Should succeed for already processed inode")

    def test_dry_run_preserves_source_files(self):
        """Test that dry-run mode doesn't modify source files"""
        test_file = self.source_dir / "test.txt"
        test_file.write_text("test content")
        dest_file = self.dest_dir / "moved.txt"

        success = self.mover.move_hardlink_group(test_file, dest_file)

        self.assertTrue(success, "Dry-run should report success")
        self.assertTrue(test_file.exists(), "Source file should still exist in dry-run")
        self.assertFalse(
            dest_file.exists(), "Destination file should not be created in dry-run"
        )

    def test_ownership_preservation_warning_suggests_sudo(self):
        """Test that ownership warning suggests sudo when not root"""
        source_file = self.source_dir / "test.txt"
        source_file.write_text("content")
        dest_file = self.dest_dir / "moved.txt"

        real_mover = CrossFilesystemMover(
            source_file,
            dest_file,
            dry_run=False,
            quiet=True,
            dir_manager=DirectoryManager(dry_run=False),
        )

        # Mock os.geteuid to simulate non-root
        with patch("os.geteuid", return_value=1000):
            with patch(
                "os.chown", side_effect=PermissionError("Operation not permitted")
            ):
                with self.assertLogs(level="WARNING") as log:
                    result = real_mover.create_file(source_file, dest_file)
                    print(f"Result: {result}")
                    print(f"Log output: {log.output}")

                    # Check that warning suggests sudo
                    warning_msg = log.output[0] if log.output else ""
                    self.assertIn("run with sudo", warning_msg.lower())

    def test_ownership_preservation_warning_no_sudo_when_root(self):
        """Test that ownership warning doesn't suggest sudo when already root"""
        source_file = self.source_dir / "test.txt"
        source_file.write_text("content")
        dest_file = self.dest_dir / "moved.txt"

        real_mover = CrossFilesystemMover(
            source_file,
            dest_file,
            dry_run=False,
            quiet=True,
            dir_manager=DirectoryManager(dry_run=False),
        )

        # Mock os.geteuid to simulate root
        with patch("os.geteuid", return_value=0):
            with patch(
                "os.chown", side_effect=PermissionError("Operation not permitted")
            ):
                with patch("shutil.copy2"):  # Ensure file creation succeeds
                    with patch("os.chmod"):  # Ensure chmod succeeds
                        with self.assertLogs(level="WARNING") as log:
                            result = real_mover.create_file(source_file, dest_file)
                            self.assertTrue(result)

                            # Check that warning doesn't suggest sudo
                            warning_msg = log.output[0]
                            self.assertNotIn("sudo", warning_msg.lower())
                            self.assertIn("Could not preserve ownership", warning_msg)

    def test_comprehensive_scan_subprocess_error(self):
        """Test comprehensive scan with subprocess error"""
        mover = CrossFilesystemMover(
            self.source_dir,
            self.dest_dir,
            dry_run=True,
            quiet=True,
            dir_manager=DirectoryManager(),
            comprehensive_scan=True,
        )

        with patch("subprocess.run", side_effect=OSError("Command not found")):
            with self.assertRaises(RuntimeError) as context:
                mover._build_hardlink_index()

            self.assertIn("comprehensive", str(context.exception))

    def test_find_hardlinks_stat_error(self):
        """Test find_hardlinks with stat error"""
        test_file = self.source_dir / "test.txt"
        test_file.write_text("content")

        mover = CrossFilesystemMover(
            self.source_dir,
            self.dest_dir,
            dry_run=True,
            quiet=True,
            dir_manager=DirectoryManager(),
        )

        with patch.object(Path, "stat", side_effect=OSError("Permission denied")):
            result = mover.find_hardlinks(test_file)
            self.assertEqual(result, [test_file])

    def test_temp_file_cleanup_mechanisms(self):
        """Test temp file cleanup"""
        mover = CrossFilesystemMover(
            self.source_dir,
            self.dest_dir,
            dry_run=False,
            quiet=True,
            dir_manager=DirectoryManager(dry_run=False),
        )

        temp_file = self.temp_dir / "temp_test.txt"
        temp_file.write_text("temp")

        mover._track_temp_file(temp_file)
        self.assertIn(temp_file, mover.temp_files)

        mover._cleanup_temp_files()
        self.assertFalse(temp_file.exists())

    def test_move_directory_cross_filesystem(self):
        """Test move_directory method directly"""
        test_dir = self.source_dir / "test_dir"
        test_dir.mkdir()
        (test_dir / "file1.txt").write_text("content1")

        real_mover = CrossFilesystemMover(
            test_dir,
            self.dest_dir / "moved_dir",
            dry_run=False,
            quiet=True,
            dir_manager=DirectoryManager(dry_run=False),
        )

        with patch.object(real_mover, "_find_mount_point", return_value=self.temp_dir):
            with patch("subprocess.run") as mock_run:
                mock_run.return_value.returncode = 0
                mock_run.return_value.stdout = ""

                success = real_mover.move_directory()

        self.assertTrue(success)


class TestFilesystemDetection(unittest.TestCase):
    """Test filesystem detection logic"""

    def setUp(self):
        self.temp_dir = Path(tempfile.mkdtemp())
        self.addCleanup(shutil.rmtree, self.temp_dir, ignore_errors=True)

    @staticmethod
    def make_stat_side_effect(dev_ids):
        """Helper to create stat side effect with device IDs"""
        call_count = -1

        def side_effect(*args, **kwargs):
            nonlocal call_count
            call_count += 1
            return type(
                "Stat",
                (),
                {
                    "st_dev": dev_ids[min(call_count, len(dev_ids) - 1)],
                    "st_mode": 0o100644,  # Regular file mode
                },
            )()

        return side_effect

    def test_same_filesystem_detection(self):
        """Test detection of same filesystem using device IDs"""

        source_file = self.temp_dir / "source.txt"
        dest_file = self.temp_dir / "dest.txt"
        source_file.write_text("test")

        with patch("pathlib.Path.stat", side_effect=self.make_stat_side_effect([123])):
            mover = FileMover(source_file, dest_file, dry_run=True)
            result = mover._detect_same_filesystem()

            self.assertTrue(
                result, "Same device IDs should be detected as same filesystem"
            )

    def test_different_filesystem_detection(self):
        """Test detection of different filesystems using device IDs"""

        source_file = self.temp_dir / "source.txt"
        dest_file = self.temp_dir / "dest.txt"
        source_file.write_text("test")

        # First create mover to get through initialization
        mover = FileMover(source_file, dest_file, dry_run=True)

        # Now mock stat for the actual detection call
        with patch(
            "pathlib.Path.stat", side_effect=self.make_stat_side_effect([123, 456])
        ):
            result = mover._detect_same_filesystem()

            self.assertFalse(
                result,
                "Different device IDs should be detected as different filesystems",
            )


class TestPerformanceOptimizations(unittest.TestCase):
    """Test performance optimizations"""

    def test_memory_index_vs_repeated_find(self):
        """Test that memory index avoids repeated subprocess calls"""
        temp_dir = Path(tempfile.mkdtemp())
        try:
            # Create source and dest directories first
            source_dir = temp_dir / "source"
            dest_dir = temp_dir / "dest"
            source_dir.mkdir()
            dest_dir.mkdir()

            mover = CrossFilesystemMover(source_dir, dest_dir, dry_run=True, quiet=True)

            # Mock subprocess to count calls
            with patch("subprocess.run") as mock_run:
                mock_run.return_value.returncode = 0
                mock_run.return_value.stdout = "12345 /path/file.txt\n"

                # Create mock file with hardlinks
                mock_file = MagicMock()
                mock_file.stat.return_value.st_nlink = 2
                mock_file.stat.return_value.st_ino = 12345

                # First call should build index
                mover.find_hardlinks(mock_file)
                first_call_count = mock_run.call_count

                # Second call should use cached index
                mover.find_hardlinks(mock_file)
                second_call_count = mock_run.call_count

                # Should not make additional subprocess calls
                self.assertEqual(
                    first_call_count,
                    second_call_count,
                    "Second call should use cached index, not make new subprocess call",
                )
        finally:
            shutil.rmtree(temp_dir, ignore_errors=True)


if __name__ == "__main__":
    unittest.main()
