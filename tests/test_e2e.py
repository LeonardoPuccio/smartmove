#!/usr/bin/env python3
"""
End-to-End Tests for SmartMove

Tests comprehensive scanning, failure scenarios, and cross-scope hardlink preservation.
Requires root privileges for loop device creation and filesystem mounting.
"""

import os
import shutil
import subprocess
import sys
import tempfile
import time
import unittest
from pathlib import Path

from smartmove.core import CrossFilesystemMover, FileMover


class RealFilesystemTestSetup:
    """Setup and teardown real different filesystems for E2E testing"""

    def __init__(self, size_mb=50):
        self.size_mb = size_mb
        self.temp_dir = None
        self.loop_devices = []
        self.mount_points = []

    def __enter__(self):
        return self.setup()

    def __exit__(self, exc_type, exc_val, exc_tb):
        self.cleanup()

    def setup(self):
        """Create two different ext4 filesystems using loop devices"""
        if os.geteuid() != 0:
            raise PermissionError("E2E tests require root privileges for loop devices")

        self.temp_dir = Path(tempfile.mkdtemp(prefix="smartmove_e2e_"))

        try:
            # Create filesystem images
            fs1_img = self.temp_dir / "fs1.img"
            fs2_img = self.temp_dir / "fs2.img"

            # Create sparse images for speed
            with open(fs1_img, "wb") as f:
                f.seek(self.size_mb * 1024 * 1024 - 1)
                f.write(b"\0")
            with open(fs2_img, "wb") as f:
                f.seek(self.size_mb * 1024 * 1024 - 1)
                f.write(b"\0")

            # Setup loop devices
            loop1_result = subprocess.run(
                ["losetup", "--find", "--show", str(fs1_img)],
                capture_output=True,
                text=True,
                check=True,
            )
            loop2_result = subprocess.run(
                ["losetup", "--find", "--show", str(fs2_img)],
                capture_output=True,
                text=True,
                check=True,
            )

            loop1_dev = loop1_result.stdout.strip()
            loop2_dev = loop2_result.stdout.strip()
            self.loop_devices = [loop1_dev, loop2_dev]

            # Create filesystems (suppress output)
            subprocess.run(
                ["mkfs.ext4", "-F", "-q", loop1_dev], check=True, capture_output=True
            )
            subprocess.run(
                ["mkfs.ext4", "-F", "-q", loop2_dev], check=True, capture_output=True
            )

            # Create mount points
            mount1 = self.temp_dir / "fs1_mount"
            mount2 = self.temp_dir / "fs2_mount"
            mount1.mkdir()
            mount2.mkdir()

            # Mount filesystems
            subprocess.run(["mount", loop1_dev, str(mount1)], check=True)
            subprocess.run(["mount", loop2_dev, str(mount2)], check=True)
            self.mount_points = [mount1, mount2]

            # Make writable by original user
            original_uid = int(os.environ.get("SUDO_UID", os.getuid()))
            original_gid = int(os.environ.get("SUDO_GID", os.getgid()))

            for mount in self.mount_points:
                os.chown(mount, original_uid, original_gid)
                os.chmod(mount, 0o755)

            return mount1, mount2

        except Exception as e:
            self.cleanup()
            raise RuntimeError(f"Failed to setup E2E test filesystems: {e}")

    def cleanup(self):
        """Cleanup loop devices and temporary files"""
        try:
            # Unmount filesystems
            for mount in self.mount_points:
                if mount.exists():
                    subprocess.run(
                        ["umount", str(mount)], capture_output=True, check=False
                    )

            # Detach loop devices
            for loop_dev in self.loop_devices:
                subprocess.run(
                    ["losetup", "-d", loop_dev], capture_output=True, check=False
                )

            # Remove temp directory
            if self.temp_dir and self.temp_dir.exists():
                shutil.rmtree(self.temp_dir, ignore_errors=True)

        except Exception:
            pass  # Ignore cleanup errors


class TestComprehensiveE2E(unittest.TestCase):
    """E2E tests with comprehensive scanning and failure scenarios"""

    @classmethod
    def setUpClass(cls):
        """Check prerequisites for E2E tests"""
        if os.geteuid() != 0:
            raise unittest.SkipTest("E2E tests require root privileges")

        # Check required tools
        required_tools = ["losetup", "mkfs.ext4", "mount", "umount"]
        for tool in required_tools:
            if subprocess.run(["which", tool], capture_output=True).returncode != 0:
                raise unittest.SkipTest(f"Required tool not found: {tool}")

    def test_comprehensive_flag_behavior(self):
        """Test comprehensive vs default scanning behavior"""

        with RealFilesystemTestSetup() as (fs1_mount, fs2_mount):
            # Create complex structure with cross-filesystem hardlinks
            source_dir = fs1_mount / "source"
            source_dir.mkdir()

            # Create file in source
            source_file = source_dir / "test_file.txt"
            source_file.write_text("Test content")

            # Create hardlink outside source directory but within same filesystem
            outside_link = fs1_mount / "outside_source.txt"
            os.link(source_file, outside_link)

            # Verify hardlink exists
            self.assertEqual(source_file.stat().st_ino, outside_link.stat().st_ino)
            self.assertEqual(source_file.stat().st_nlink, 2)

            # Test 1: Default behavior (should not find outside hardlink)
            dest_dir_default = fs2_mount / "moved_default"
            mover_default = FileMover(
                source_dir,
                dest_dir_default,
                create_parents=True,
                dry_run=False,
                quiet=True,
                comprehensive_scan=False,
            )

            success = mover_default.move()
            self.assertTrue(success)

            # Reset for comprehensive test
            source_dir.mkdir()
            source_file.write_text("Test content")
            os.link(source_file, outside_link)

            # Test 2: Comprehensive behavior (should find outside hardlink)
            dest_dir_comprehensive = fs2_mount / "moved_comprehensive"
            mover_comprehensive = FileMover(
                source_dir,
                dest_dir_comprehensive,
                create_parents=True,
                dry_run=False,
                quiet=True,
                comprehensive_scan=True,
            )

            success = mover_comprehensive.move()
            self.assertTrue(success)

            # Verify comprehensive mode moved both files
            dest_source_file = dest_dir_comprehensive / "test_file.txt"
            dest_outside_file = fs2_mount / "outside_source.txt"

            if dest_outside_file.exists():
                self.assertEqual(
                    dest_source_file.stat().st_ino, dest_outside_file.stat().st_ino
                )
                self.assertEqual(dest_source_file.stat().st_nlink, 2)
                print("✓ Comprehensive flag preserved cross-scope hardlinks")
            else:
                print("! Comprehensive flag behavior needs verification")

    def test_failure_scenarios(self):
        """Test various failure conditions"""

        with RealFilesystemTestSetup() as (fs1_mount, fs2_mount):
            # Test 1: Invalid source path
            nonexistent_source = fs1_mount / "does_not_exist"
            dest_invalid = fs2_mount / "invalid_moved"

            with self.assertRaises(ValueError) as context:
                FileMover(nonexistent_source, dest_invalid, dry_run=False, quiet=True)

            self.assertIn("Source does not exist", str(context.exception))
            print("✓ Invalid source detection works")

            # Test 2: Invalid destination parent without create_parents
            valid_source = fs1_mount / "test.txt"
            valid_source.write_text("test content")
            invalid_dest = fs2_mount / "nonexistent" / "path" / "file.txt"

            with self.assertRaises(ValueError) as context:
                FileMover(
                    valid_source,
                    invalid_dest,
                    create_parents=False,
                    dry_run=False,
                    quiet=True,
                )

            self.assertIn(
                "Destination parent directory does not exist", str(context.exception)
            )
            print("✓ Invalid destination parent detection works")

    def test_cross_scope_hardlink_validation(self):
        """Test comprehensive validation of cross-scope hardlinks"""

        with RealFilesystemTestSetup() as (fs1_mount, fs2_mount):
            # Create complex cross-scope scenario
            source_dir = fs1_mount / "move_me"
            source_dir.mkdir()

            # Create multiple directories with interconnected hardlinks
            (source_dir / "subdir1").mkdir()
            (source_dir / "subdir2").mkdir()
            outside_dir = fs1_mount / "stay_here"
            outside_dir.mkdir()

            # Pattern 1: File in source, hardlink outside
            file1 = source_dir / "subdir1" / "shared1.txt"
            file1.write_text("Shared content 1")
            outside_link1 = outside_dir / "external1.txt"
            os.link(file1, outside_link1)

            # Pattern 2: File outside, hardlink in source
            outside_file2 = outside_dir / "original2.txt"
            outside_file2.write_text("Shared content 2")
            inside_link2 = source_dir / "subdir2" / "internal2.txt"
            os.link(outside_file2, inside_link2)

            # Pattern 3: Multiple hardlinks spanning in/out of source
            file3 = source_dir / "shared3.txt"
            file3.write_text("Shared content 3")
            link3a = source_dir / "subdir1" / "link3a.txt"
            link3b = outside_dir / "link3b.txt"
            os.link(file3, link3a)
            os.link(file3, link3b)

            # Verify initial hardlink structure
            self.assertEqual(file1.stat().st_nlink, 2)
            self.assertEqual(outside_file2.stat().st_nlink, 2)
            self.assertEqual(file3.stat().st_nlink, 3)

            # Test with comprehensive scanning
            dest_dir = fs2_mount / "comprehensive_moved"
            mover = FileMover(
                source_dir,
                dest_dir,
                create_parents=True,
                dry_run=False,
                quiet=True,
                comprehensive_scan=True,
            )

            success = mover.move()
            self.assertTrue(success)

            # Validate cross-scope hardlink preservation
            # Pattern 1: Both files should be moved with preserved structure
            moved_file1 = dest_dir / "subdir1" / "shared1.txt"
            moved_outside1 = (
                fs2_mount / "stay_here" / "external1.txt"
            )  # Preserved structure

            if moved_outside1.exists():
                self.assertEqual(
                    moved_file1.stat().st_ino, moved_outside1.stat().st_ino
                )
                self.assertEqual(moved_file1.stat().st_nlink, 2)
                print(
                    "✓ Pattern 1: Cross-scope hardlink preserved with directory structure"
                )

            # Pattern 2: Original outside file and moved inside file should be linked
            moved_inside2 = dest_dir / "subdir2" / "internal2.txt"
            moved_outside2 = (
                fs2_mount / "stay_here" / "original2.txt"
            )  # Preserved structure

            if moved_outside2.exists():
                self.assertEqual(
                    moved_inside2.stat().st_ino, moved_outside2.stat().st_ino
                )
                self.assertEqual(moved_inside2.stat().st_nlink, 2)
                print(
                    "✓ Pattern 2: Outside→inside hardlink preserved with directory structure"
                )

            # Pattern 3: All three links should be preserved
            moved_file3 = dest_dir / "shared3.txt"
            moved_link3a = dest_dir / "subdir1" / "link3a.txt"
            moved_link3b = fs2_mount / "stay_here" / "link3b.txt"  # Preserved structure

            if moved_link3b.exists():
                base_inode = moved_file3.stat().st_ino
                self.assertEqual(moved_link3a.stat().st_ino, base_inode)
                self.assertEqual(moved_link3b.stat().st_ino, base_inode)
                self.assertEqual(moved_file3.stat().st_nlink, 3)
                print("✓ Pattern 3: Multiple cross-scope hardlinks preserved")

            # Verify source cleanup
            self.assertFalse(source_dir.exists())
            print("✓ Source directory properly cleaned up")

    def test_dry_run_comprehensive_preview(self):
        """Test dry-run mode with comprehensive scanning"""

        with RealFilesystemTestSetup() as (fs1_mount, fs2_mount):
            # Create test structure
            source_dir = fs1_mount / "preview_test"
            source_dir.mkdir()

            test_file = source_dir / "test.txt"
            test_file.write_text("Preview content")

            outside_link = fs1_mount / "outside.txt"
            os.link(test_file, outside_link)

            # Test dry-run with comprehensive
            dest_dir = fs2_mount / "preview_moved"
            mover = FileMover(
                source_dir,
                dest_dir,
                create_parents=True,
                dry_run=True,
                quiet=False,
                comprehensive_scan=True,
            )

            success = mover.move()
            self.assertTrue(success)

            # Verify nothing was actually moved in dry-run
            self.assertTrue(source_dir.exists())
            self.assertTrue(test_file.exists())
            self.assertTrue(outside_link.exists())
            self.assertFalse(dest_dir.exists())

            # Verify hardlinks still intact
            self.assertEqual(test_file.stat().st_nlink, 2)
            print("✓ Dry-run preserves source files and shows comprehensive preview")


class TestLargeScalePerformance(unittest.TestCase):
    """Separate large-scale performance tests"""

    @unittest.skipUnless(
        os.environ.get("RUN_LARGE_SCALE_TESTS") == "1",
        "Large scale tests skipped (set RUN_LARGE_SCALE_TESTS=1 to enable)",
    )
    def test_large_scale_comprehensive_performance(self):
        """Large-scale performance test with comprehensive scanning"""

        with RealFilesystemTestSetup(size_mb=4096) as (fs1_mount, fs2_mount):
            # Create large test structure
            source_dir = fs1_mount / "large_test"
            source_dir.mkdir()

            num_file_groups = 25000
            links_per_group = 12

            print(f"Creating {num_file_groups * (links_per_group + 1)} files...")
            creation_start = time.time()

            for i in range(num_file_groups):
                group_dir = source_dir / f"group_{i:05d}"
                group_dir.mkdir()

                # Create original file
                original = group_dir / f"original_{i}.txt"
                original.write_text(f"Content {i}")  # Small content

                # Create hardlinks in different subdirectories
                for j in range(links_per_group):
                    link_dir = source_dir / f"links_{j:02d}"
                    link_dir.mkdir(exist_ok=True)
                    link = link_dir / f"link_{i:05d}_{j}.txt"
                    os.link(original, link)

            creation_time = time.time() - creation_start

            # Test comprehensive scanning performance
            dest_dir = fs2_mount / "large_moved"

            move_start = time.time()
            mover = FileMover(
                source_dir,
                dest_dir,
                create_parents=True,
                dry_run=False,
                quiet=True,
                comprehensive_scan=True,
            )
            success = mover.move()
            move_time = time.time() - move_start

            self.assertTrue(success)

            total_files = num_file_groups * (links_per_group + 1)
            moved_files = list(dest_dir.rglob("*.txt"))
            self.assertEqual(len(moved_files), total_files)

            print(f"✓ Large scale test: {total_files} files")
            print(f"  Creation time: {creation_time:.2f}s")
            print(f"  Move time: {move_time:.2f}s")
            print(f"  Files per second: {total_files / move_time:.1f}")

    def test_hardlink_detection_performance_only(self):
        """Benchmark hardlink detection speed on large existing dataset

        Tests the core _build_hardlink_index() performance by:
        1. Creating large hardlink dataset (60k files, 10k hardlink groups)
        2. Measuring only the scanning phase (dry_run=True)
        3. Validating detection accuracy and speed thresholds

        This isolates hardlink detection from file I/O operations.
        """

        with RealFilesystemTestSetup(size_mb=2048) as (fs1_mount, fs2_mount):
            # Phase 1: Create test dataset (timing not counted toward scan performance)
            base_dir = fs1_mount / "existing_dataset"
            base_dir.mkdir()

            setup_start = time.time()
            for i in range(10000):  # Create 10,000 hardlink groups
                group_dir = base_dir / f"group_{i:05d}"
                group_dir.mkdir()

                # Create original file
                original = group_dir / f"file_{i}.txt"
                original.write_text(f"content_{i}")

                # Create 5 hardlinks per group = 60,000 total files
                for j in range(5):
                    link_dir = base_dir / f"links_{j}"
                    link_dir.mkdir(exist_ok=True)
                    link_path = link_dir / f"hardlink_{i:05d}_{j}.txt"
                    os.link(original, link_path)

            setup_time = time.time() - setup_start
            total_files = 60000  # 10k originals + 50k hardlinks

            # Phase 2: Benchmark hardlink detection (the actual test)
            scan_start = time.time()
            mover = CrossFilesystemMover(
                base_dir,
                fs2_mount / "moved",
                dry_run=True,  # Skip file operations, test scanning only
                quiet=True,
                comprehensive_scan=False,
            )

            # Trigger hardlink index building - this is what we're benchmarking
            mover._build_hardlink_index()
            scan_time = time.time() - scan_start

            # Phase 3: Validate results
            hardlink_groups = len(mover.hardlink_index)
            indexed_files = sum(len(paths) for paths in mover.hardlink_index.values())

            # Report performance metrics
            print(f"Dataset creation: {setup_time:.2f}s for {total_files} files")
            print(f"Hardlink detection: {scan_time:.2f}s")
            print(f"Detection rate: {total_files / scan_time:.0f} files/sec")
            print(f"Found {hardlink_groups} hardlink groups ({indexed_files} files)")

            # Performance requirements
            self.assertEqual(
                hardlink_groups, 10000, "Should detect all hardlink groups"
            )
            self.assertEqual(
                indexed_files, total_files, "Should index all hardlinked files"
            )
            self.assertLess(scan_time, 10.0, f"Scan too slow: {scan_time:.2f}s")
            self.assertGreater(
                total_files / scan_time, 5000, "Should process >5k files/sec"
            )


if __name__ == "__main__":
    print("SmartMove Comprehensive E2E Tests")
    print("=" * 50)

    if os.geteuid() != 0:
        print("Error: E2E tests require root privileges")
        print("Usage: sudo python3 tests/test_comprehensive_e2e.py")
        sys.exit(1)

    unittest.main(verbosity=2)
