#!/usr/bin/env python3
"""
End-to-End Tests for SmartMove

Tests complete system behavior with real different filesystems.
Requires root privileges and loop device support.
"""

import os
import sys
import subprocess
import tempfile
import unittest
import time
from pathlib import Path


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
            with open(fs1_img, 'wb') as f:
                f.seek(self.size_mb * 1024 * 1024 - 1)
                f.write(b'\0')
            with open(fs2_img, 'wb') as f:
                f.seek(self.size_mb * 1024 * 1024 - 1) 
                f.write(b'\0')
            
            # Setup loop devices
            loop1_result = subprocess.run(
                ['losetup', '--find', '--show', str(fs1_img)], 
                capture_output=True, text=True, check=True
            )
            loop2_result = subprocess.run(
                ['losetup', '--find', '--show', str(fs2_img)], 
                capture_output=True, text=True, check=True
            )
            
            loop1_dev = loop1_result.stdout.strip()
            loop2_dev = loop2_result.stdout.strip()
            self.loop_devices = [loop1_dev, loop2_dev]
            
            # Create filesystems (suppress output)
            subprocess.run(
                ['mkfs.ext4', '-F', '-q', loop1_dev], 
                check=True, capture_output=True
            )
            subprocess.run(
                ['mkfs.ext4', '-F', '-q', loop2_dev], 
                check=True, capture_output=True
            )
            
            # Create mount points
            mount1 = self.temp_dir / "fs1_mount"
            mount2 = self.temp_dir / "fs2_mount"
            mount1.mkdir()
            mount2.mkdir()
            
            # Mount filesystems
            subprocess.run(['mount', loop1_dev, str(mount1)], check=True)
            subprocess.run(['mount', loop2_dev, str(mount2)], check=True)
            self.mount_points = [mount1, mount2]
            
            # Make writable by original user
            original_uid = int(os.environ.get('SUDO_UID', os.getuid()))
            original_gid = int(os.environ.get('SUDO_GID', os.getgid()))
            
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
                        ['umount', str(mount)], 
                        capture_output=True, check=False
                    )
            
            # Detach loop devices
            for loop_dev in self.loop_devices:
                subprocess.run(
                    ['losetup', '-d', loop_dev], 
                    capture_output=True, check=False
                )
            
            # Remove temp directory
            if self.temp_dir and self.temp_dir.exists():
                import shutil
                shutil.rmtree(self.temp_dir, ignore_errors=True)
                
        except Exception:
            pass  # Ignore cleanup errors


class TestE2ECrossFilesystemOperations(unittest.TestCase):
    """End-to-end tests with real different filesystems"""
    
    @classmethod
    def setUpClass(cls):
        """Check prerequisites for E2E tests"""
        if os.geteuid() != 0:
            raise unittest.SkipTest("E2E tests require root privileges")
        
        # Check required tools
        required_tools = ['losetup', 'mkfs.ext4', 'mount', 'umount']
        for tool in required_tools:
            if subprocess.run(['which', tool], capture_output=True).returncode != 0:
                raise unittest.SkipTest(f"Required tool not found: {tool}")
    
    def test_real_cross_filesystem_hardlink_preservation(self):
        """Test complete hardlink preservation across real filesystems"""
        
        with RealFilesystemTestSetup() as (fs1_mount, fs2_mount):
            
            # Create comprehensive test structure
            source_dir = fs1_mount / "test_source"
            source_dir.mkdir()
            
            # Create files with various hardlink patterns
            
            # 1. Simple hardlink group
            original = source_dir / "original.txt"
            original.write_text("Original content")
            
            simple_link = source_dir / "subdir1" / "simple_link.txt"
            simple_link.parent.mkdir()
            os.link(original, simple_link)
            
            # 2. Complex nested hardlinks
            nested_original = source_dir / "deep" / "nested" / "file.txt"
            nested_original.parent.mkdir(parents=True)
            nested_original.write_text("Nested content")
            
            nested_link1 = source_dir / "deep" / "link1.txt"
            nested_link2 = source_dir / "alternative" / "path" / "link2.txt"
            nested_link2.parent.mkdir(parents=True)
            
            os.link(nested_original, nested_link1)
            os.link(nested_original, nested_link2)
            
            # 3. Cross-scope hardlink (outside source tree)
            cross_scope_original = fs1_mount / "outside_source.txt"
            cross_scope_original.write_text("Cross-scope content")
            
            cross_scope_link = source_dir / "inside_link.txt"
            os.link(cross_scope_original, cross_scope_link)
            
            # Verify initial state
            self.assertEqual(original.stat().st_nlink, 2)
            self.assertEqual(nested_original.stat().st_nlink, 3)
            self.assertEqual(cross_scope_original.stat().st_nlink, 2)
            
            # Import FileMover
            sys.path.insert(0, str(Path(__file__).parent.parent))
            from file_mover import FileMover
            
            # Test SmartMove across real different filesystems
            dest_dir = fs2_mount / "moved_source"
            start_time = time.time()
            
            mover = FileMover(
                source_dir, dest_dir, 
                create_parents=True, dry_run=False, quiet=True
            )
            
            # Verify different filesystems detected
            self.assertFalse(mover._detect_same_filesystem())
            
            # Execute move
            success = mover.move()
            
            end_time = time.time()
            
            self.assertTrue(success, "E2E move should succeed")
            
            # Verify destination structure exists
            dest_original = dest_dir / "original.txt"
            dest_simple_link = dest_dir / "subdir1" / "simple_link.txt"
            dest_nested_original = dest_dir / "deep" / "nested" / "file.txt"
            dest_nested_link1 = dest_dir / "deep" / "link1.txt"
            dest_nested_link2 = dest_dir / "alternative" / "path" / "link2.txt"
            dest_cross_scope_link = dest_dir / "inside_link.txt"
            
            # Verify all files moved
            self.assertTrue(dest_original.exists())
            self.assertTrue(dest_simple_link.exists())
            self.assertTrue(dest_nested_original.exists())
            self.assertTrue(dest_nested_link1.exists())
            self.assertTrue(dest_nested_link2.exists())
            self.assertTrue(dest_cross_scope_link.exists())
            
            # Verify hardlinks preserved
            
            # Simple group
            simple_inode = dest_original.stat().st_ino
            self.assertEqual(dest_simple_link.stat().st_ino, simple_inode)
            self.assertEqual(dest_original.stat().st_nlink, 2)
            
            # Nested group
            nested_inode = dest_nested_original.stat().st_ino
            self.assertEqual(dest_nested_link1.stat().st_ino, nested_inode)
            self.assertEqual(dest_nested_link2.stat().st_ino, nested_inode)
            self.assertEqual(dest_nested_original.stat().st_nlink, 3)
            
            # Cross-scope group
            if (fs2_mount / "outside_source.txt").exists():
                cross_scope_dest_inode = (fs2_mount / "outside_source.txt").stat().st_ino
                self.assertEqual(dest_cross_scope_link.stat().st_ino, cross_scope_dest_inode)
                self.assertEqual((fs2_mount / "outside_source.txt").stat().st_nlink, 2)
            
            # Verify content preserved
            self.assertEqual(dest_original.read_text(), "Original content")
            self.assertEqual(dest_nested_original.read_text(), "Nested content")
            self.assertEqual(dest_cross_scope_link.read_text(), "Cross-scope content")
            
            # Verify source cleaned up
            self.assertFalse(source_dir.exists())
            
            duration = end_time - start_time
            print(f"✅ E2E test completed in {duration:.2f}s")
    
    def test_real_filesystem_performance_benchmark(self):
        """Benchmark performance with real filesystems and many hardlinks"""
        
        with RealFilesystemTestSetup() as (fs1_mount, fs2_mount):
            
            # Create performance test structure
            perf_dir = fs1_mount / "perf_test"
            perf_dir.mkdir()
            
            # Create many files with hardlinks for realistic performance test
            num_file_groups = 25
            links_per_group = 3
            
            creation_start = time.time()
            
            for i in range(num_file_groups):
                # Create original file
                original = perf_dir / f"group_{i}" / f"original_{i}.txt"
                original.parent.mkdir(exist_ok=True)
                original.write_text(f"Performance test content {i}")
                
                # Create hardlinks
                for j in range(links_per_group):
                    link_dir = perf_dir / f"links_{j}"
                    link_dir.mkdir(exist_ok=True)
                    link = link_dir / f"link_{i}_{j}.txt"
                    os.link(original, link)
            
            creation_time = time.time() - creation_start
            
            # Verify test structure
            total_files = num_file_groups * (links_per_group + 1)
            created_files = list(perf_dir.rglob("*.txt"))
            self.assertEqual(len(created_files), total_files)
            
            # Test SmartMove performance
            sys.path.insert(0, str(Path(__file__).parent.parent))
            from file_mover import FileMover
            
            dest_dir = fs2_mount / "moved_perf"
            
            move_start = time.time()
            mover = FileMover(
                perf_dir, dest_dir,
                create_parents=True, dry_run=False, quiet=True
            )
            success = mover.move()
            move_time = time.time() - move_start
            
            self.assertTrue(success, "Performance test should succeed")
            
            # Verify all files moved with hardlinks preserved
            moved_files = list(dest_dir.rglob("*.txt"))
            self.assertEqual(len(moved_files), total_files)
            
            # Sample verification of hardlink preservation
            for i in range(0, min(5, num_file_groups)):  # Check first 5 groups
                dest_original = dest_dir / f"group_{i}" / f"original_{i}.txt"
                dest_links = [dest_dir / f"links_{j}" / f"link_{i}_{j}.txt" 
                             for j in range(links_per_group)]
                
                if dest_original.exists():
                    original_inode = dest_original.stat().st_ino
                    original_links = dest_original.stat().st_nlink
                    
                    # Verify hardlinks
                    actual_links = 1  # Count original
                    for link in dest_links:
                        if link.exists() and link.stat().st_ino == original_inode:
                            actual_links += 1
                    
                    expected_links = links_per_group + 1
                    self.assertEqual(actual_links, expected_links, 
                                   f"Group {i} should have {expected_links} hardlinks")
                    self.assertEqual(original_links, expected_links)
            
            # Performance assertions
            max_acceptable_time = 60.0  # 1 minute for this test size
            self.assertLess(move_time, max_acceptable_time, 
                           f"Move took too long: {move_time:.2f}s")
            
            print(f"✅ Performance test: {total_files} files created in {creation_time:.2f}s, "
                  f"moved in {move_time:.2f}s")
    
    def test_real_filesystem_edge_cases(self):
        """Test edge cases with real filesystems"""
        
        with RealFilesystemTestSetup() as (fs1_mount, fs2_mount):
            
            # Test deeply nested paths
            deep_source = fs1_mount / "very" / "deep" / "nested" / "directory" / "structure"
            deep_source.mkdir(parents=True)
            
            deep_file = deep_source / "deep_file.txt"
            deep_file.write_text("Deep content")
            
            # Test with spaces and special characters in paths
            special_dir = fs1_mount / "path with spaces" / "special-chars_123"
            special_dir.mkdir(parents=True)
            
            special_file = special_dir / "file with spaces.txt"
            special_file.write_text("Special content")
            
            # Create hardlink between deep and special locations
            cross_link = deep_source / "link_to_special.txt"
            os.link(special_file, cross_link)
            
            # Test moving deep structure
            sys.path.insert(0, str(Path(__file__).parent.parent))
            from file_mover import FileMover
            
            dest_deep = fs2_mount / "moved_deep"
            mover = FileMover(
                fs1_mount / "very", dest_deep,
                create_parents=True, dry_run=False, quiet=True
            )
            
            success = mover.move()
            self.assertTrue(success, "Deep path move should succeed")
            
            # Verify deep file moved
            moved_deep_file = dest_deep / "deep" / "nested" / "directory" / "structure" / "deep_file.txt"
            self.assertTrue(moved_deep_file.exists())
            self.assertEqual(moved_deep_file.read_text(), "Deep content")
            
            # Verify cross-directory hardlink handling
            moved_cross_link = dest_deep / "deep" / "nested" / "directory" / "structure" / "link_to_special.txt"
            if moved_cross_link.exists():
                # If hardlink was found and moved, verify content
                self.assertEqual(moved_cross_link.read_text(), "Special content")


def create_e2e_runner():
    """Create script to run E2E tests with proper setup"""
    runner_content = '''#!/bin/bash
# E2E Test Runner for SmartMove

set -e

if [ "$EUID" -ne 0 ]; then
    echo "Error: E2E tests require root privileges"
    echo "Usage: sudo ./run_e2e_tests.sh"
    exit 1
fi

echo "Running SmartMove E2E Tests..."
echo "This will create temporary loop devices and filesystems"
echo

# Run the tests
python3 -m pytest tests/test_e2e.py -v

echo
echo "E2E tests completed!"
'''
    
    runner_path = Path("run_e2e_tests.sh")
    runner_path.write_text(runner_content)
    runner_path.chmod(0o755)
    
    return runner_path


if __name__ == '__main__':
    print("SmartMove E2E Tests")
    print("=" * 40)
    
    if len(sys.argv) > 1 and sys.argv[1] == "--create-runner":
        runner = create_e2e_runner()
        print(f"Created E2E test runner: {runner}")
        sys.exit(0)
    
    if os.geteuid() != 0:
        print("Error: E2E tests require root privileges")
        print("Usage: sudo python3 tests/test_e2e.py")
        print("Or: python3 tests/test_e2e.py --create-runner")
        sys.exit(1)
    
    unittest.main(verbosity=2)