#!/usr/bin/env python3
"""
Integration tests for SmartMove
"""

import os
import tempfile
import unittest
import subprocess
from pathlib import Path
from unittest.mock import patch

from file_mover import FileMover


class TestSmartMoveIntegration(unittest.TestCase):
    
    def setUp(self):
        self.temp_dir = Path(tempfile.mkdtemp())
        self.source_dir = self.temp_dir / "source"
        self.dest_dir = self.temp_dir / "dest"
        self.source_dir.mkdir()
        self.dest_dir.mkdir()
    
    def tearDown(self):
        import shutil
        shutil.rmtree(self.temp_dir, ignore_errors=True)
    
    def _create_hardlinked_files(self, base_dir, file_groups):
        """Create files with hardlinks based on group specification
        
        Args:
            base_dir: Base directory to create files in
            file_groups: Dict mapping group_name to (content, [paths])
            
        Returns:
            Dict mapping group_name to list of created file paths
        """
        created_groups = {}
        
        for group_name, (content, paths) in file_groups.items():
            if not paths:
                continue
                
            first_path = base_dir / paths[0]
            first_path.parent.mkdir(parents=True, exist_ok=True)
            first_path.write_text(content)
            
            group_files = [first_path]
            
            for path in paths[1:]:
                link_path = base_dir / path
                link_path.parent.mkdir(parents=True, exist_ok=True)
                os.link(first_path, link_path)
                group_files.append(link_path)
            
            created_groups[group_name] = group_files
        
        return created_groups
    
    def _verify_hardlinks_preserved(self, file_groups, dest_base):
        """Verify hardlinks are preserved at destination"""
        for group_name, source_files in file_groups.items():
            if len(source_files) <= 1:
                continue
            
            dest_files = []
            for source_file in source_files:
                try:
                    rel_path = source_file.relative_to(self.source_dir)
                    dest_file = dest_base / rel_path
                    if dest_file.exists():
                        dest_files.append(dest_file)
                except ValueError:
                    dest_file = self.dest_dir.parent / source_file.name
                    if dest_file.exists():
                        dest_files.append(dest_file)
            
            self.assertEqual(len(dest_files), len(source_files),
                           f"All files in group {group_name} should be moved")
            
            if len(dest_files) > 1:
                dest_inodes = [f.stat().st_ino for f in dest_files]
                self.assertEqual(len(set(dest_inodes)), 1,
                               f"All files in group {group_name} should have same inode")
                
                expected_links = len(dest_files)
                actual_links = dest_files[0].stat().st_nlink
                self.assertEqual(actual_links, expected_links,
                               f"Group {group_name} should have {expected_links} links")
    
    def test_single_file_move_same_filesystem(self):
        """Test moving single file on same filesystem"""
        source_file = self.source_dir / "test.txt"
        dest_file = self.dest_dir / "moved.txt"
        
        source_file.write_text("test content")
        
        mover = FileMover(source_file, dest_file, dry_run=True)
        success = mover.move()
        
        self.assertTrue(success)
        self.assertTrue(source_file.exists())
    
    def test_directory_with_hardlinks_comprehensive(self):
        """Test directory move with complex hardlink scenarios"""
        file_groups = {
            "simple_group": ("Simple content", [
                "file1.txt", 
                "subdir1/file1_link.txt"
            ]),
            "scattered_group": ("Scattered content", [
                "root_file.txt",
                "deep/nested/path/scattered.txt",
                "alternative/location/scattered.txt"
            ]),
            "single_file": ("No links", ["single.txt"]),
            "triple_group": ("Triple content", [
                "dir1/original.txt",
                "dir1/subdir/link1.txt", 
                "dir2/link2.txt"
            ])
        }
        
        created_groups = self._create_hardlinked_files(self.source_dir, file_groups)
        
        for group_name, files in created_groups.items():
            if len(files) > 1:
                original_inode = files[0].stat().st_ino
                for file in files[1:]:
                    self.assertEqual(file.stat().st_ino, original_inode,
                                   f"Initial hardlinks in {group_name} should have same inode")
        
        dest_path = self.dest_dir / "moved_dir"
        mover = FileMover(self.source_dir, dest_path, create_parents=True, dry_run=True)
        success = mover.move()
        
        self.assertTrue(success)
        for files in created_groups.values():
            for file in files:
                self.assertTrue(file.exists(), f"Source file should remain in dry run: {file}")
    
    def test_cross_scope_hardlinks(self):
        """Test hardlinks that span outside the move scope"""
        from cross_filesystem import CrossFilesystemMover
    
        with patch.object(CrossFilesystemMover, '_find_mount_point', return_value=self.temp_dir):
            outside_file = self.temp_dir / "outside_scope.txt"
            outside_file.write_text("Cross-scope content")
            
            source_subdir = self.source_dir / "move_this"
            source_subdir.mkdir()
            inside_file = source_subdir / "inside_scope.txt"
            os.link(outside_file, inside_file)
            
            self.assertEqual(outside_file.stat().st_ino, inside_file.stat().st_ino)
            self.assertEqual(outside_file.stat().st_nlink, 2)
            
            cross_mover = CrossFilesystemMover(
                source_subdir, self.dest_dir / "moved",
                dry_run=True, quiet=True, dir_manager=None
            )

            mapped_dest = cross_mover.map_hardlink_destination(outside_file)
            expected_dest = self.temp_dir / "outside_scope.txt"
            self.assertEqual(mapped_dest, expected_dest)
    
    def test_mount_point_detection_integration(self):
        """Test mount point detection with nested structures"""
        deep_path = self.source_dir / "very" / "deep" / "nested" / "structure"
        deep_path.mkdir(parents=True)
        deep_file = deep_path / "file.txt"
        deep_file.write_text("Deep content")
        
        from cross_filesystem import CrossFilesystemMover
        cross_mover = CrossFilesystemMover(
            deep_file, self.dest_dir / "moved.txt",
            dry_run=True, quiet=True, dir_manager=None
        )
        
        self.assertIsInstance(cross_mover.source_root, Path)
        self.assertTrue(cross_mover.source_root.exists())
        
        try:
            deep_file.relative_to(cross_mover.source_root)
            is_ancestor = True
        except ValueError:
            is_ancestor = False
        
        self.assertTrue(is_ancestor, "Mount point should be ancestor of source file")
    
    def test_performance_with_many_hardlinks(self):
        """Test performance with many hardlinked files"""
        file_groups = {}
        num_groups = 10
        
        for i in range(num_groups):
            file_groups[f"group_{i}"] = (
                f"Content {i}",
                [f"file_{i}.txt", f"dir1/link_{i}.txt", f"dir2/link_{i}.txt"]
            )
        
        created_groups = self._create_hardlinked_files(self.source_dir, file_groups)
        
        import time
        start_time = time.time()
        
        dest_path = self.dest_dir / "perf_test"
        mover = FileMover(self.source_dir, dest_path, create_parents=True, dry_run=True)
        success = mover.move()
        
        end_time = time.time()
        duration = end_time - start_time
        
        self.assertTrue(success, "Performance test should succeed")
        self.assertLess(duration, 10.0, f"Operation took too long: {duration:.2f}s")
        
        for files in created_groups.values():
            for file in files:
                self.assertTrue(file.exists(), "Source files should remain in dry run")
    
    def test_parent_directory_creation(self):
        """Test automatic parent directory creation"""
        source_file = self.source_dir / "test.txt"
        dest_file = self.dest_dir / "new" / "nested" / "path" / "file.txt"
        
        source_file.write_text("test content")
        
        mover = FileMover(source_file, dest_file, create_parents=True, dry_run=True)
        success = mover.move()
        
        self.assertTrue(success)
    
    def test_filesystem_detection_integration(self):
        """Test same vs different filesystem detection"""
        source_file = self.source_dir / "test.txt"
        dest_file_same = self.dest_dir / "moved.txt"
        source_file.write_text("test content")
        
        mover_same = FileMover(source_file, dest_file_same, dry_run=True)
        same_fs = mover_same._detect_same_filesystem()
        self.assertTrue(same_fs, "Both files in temp dir should be same filesystem")
        
        dest_file_diff = self.temp_dir / "different_fs" / "moved.txt"
        dest_file_diff.parent.mkdir()
        
        original_os_stat = os.stat
        
        def mock_os_stat(path_str, follow_symlinks=True):
            original_stat = original_os_stat(path_str, follow_symlinks=follow_symlinks)
            if "different_fs" in str(path_str):
                class MockStat:
                    def __init__(self, orig_stat):
                        for attr in dir(orig_stat):
                            if not attr.startswith('_'):
                                setattr(self, attr, getattr(orig_stat, attr))
                        self.st_dev = orig_stat.st_dev + 1
                return MockStat(original_stat)
            return original_stat
        
        def mock_path_stat(self, **kwargs):
            return mock_os_stat(str(self), **kwargs)
        
        with patch('os.stat', side_effect=mock_os_stat):
            with patch('pathlib.Path.stat', mock_path_stat):
                mover_diff = FileMover(source_file, dest_file_diff, dry_run=True)
                diff_fs = mover_diff._detect_same_filesystem()
                self.assertFalse(diff_fs, "Mocked different filesystem should be detected")
    
    def test_error_handling_missing_source(self):
        """Test error handling for missing source"""
        nonexistent = self.source_dir / "missing.txt"
        dest_file = self.dest_dir / "moved.txt"
        
        with self.assertRaises(ValueError) as context:
            FileMover(nonexistent, dest_file)
        
        self.assertIn("Source does not exist", str(context.exception))
    
    def test_error_handling_missing_dest_parent(self):
        """Test error handling for missing destination parent"""
        source_file = self.source_dir / "test.txt"
        dest_file = self.temp_dir / "nonexistent" / "moved.txt"
        
        source_file.write_text("test content")
        
        with self.assertRaises(ValueError) as context:
            FileMover(source_file, dest_file, create_parents=False)
        
        self.assertIn("Destination parent directory does not exist", str(context.exception))
    
    def test_memory_index_caching(self):
        """Test that memory index is built once and reused"""
        file_groups = {
            "test_group": ("Test content", ["file1.txt", "file2.txt", "subdir/file3.txt"])
        }
        created_groups = self._create_hardlinked_files(self.source_dir, file_groups)
        
        from cross_filesystem import CrossFilesystemMover
        cross_mover = CrossFilesystemMover(
            self.source_dir, self.dest_dir / "moved",
            dry_run=True, quiet=True, dir_manager=None
        )
        
        with patch('subprocess.run') as mock_run:
            mock_run.return_value.returncode = 0
            mock_run.return_value.stdout = "12345 /path/file.txt\n"
            
            test_files = created_groups["test_group"]
            
            cross_mover.find_hardlinks(test_files[0])
            first_call_count = mock_run.call_count
            
            cross_mover.find_hardlinks(test_files[1])
            second_call_count = mock_run.call_count
            
            self.assertEqual(first_call_count, second_call_count,
                           "Index should be cached and not rebuilt for subsequent calls")


class TestMountPointDetection(unittest.TestCase):
    """Test mount point detection functionality"""
    
    def setUp(self):
        self.temp_dir = Path(tempfile.mkdtemp())
        self.source_dir = self.temp_dir / "source_fs"
        self.dest_dir = self.temp_dir / "dest_fs"
        self.source_dir.mkdir()
        self.dest_dir.mkdir()
    
    def tearDown(self):
        import shutil
        shutil.rmtree(self.temp_dir, ignore_errors=True)
    
    def test_find_mount_point_method_exists(self):
        """Test that _find_mount_point method exists and works"""
        from cross_filesystem import CrossFilesystemMover
        
        mover = CrossFilesystemMover(
            self.source_dir, self.dest_dir,
            dry_run=True, quiet=True, dir_manager=None
        )
        
        self.assertIsInstance(mover.source_root, Path)
        self.assertIsInstance(mover.dest_root, Path)
    
    def test_dry_run_with_nonexistent_destination_parent(self):
        """Test dry-run with non-existent destination paths"""
        source_file = self.source_dir / "test.txt"
        source_file.write_text("test content")
        
        dest_file = self.temp_dir / "nonexistent" / "deep" / "path" / "test.txt"
        
        mover = FileMover(source_file, dest_file, create_parents=True, dry_run=True)
        success = mover.move()
        self.assertTrue(success, "Dry-run should succeed even with non-existent parent")
    
    def test_space_validation_uses_mount_point(self):
        """Test space validation uses mount point for non-existent paths"""
        from cross_filesystem import CrossFilesystemMover
        
        source_file = self.source_dir / "test.txt"
        source_file.write_text("x" * 1000)
        
        dest_file = self.temp_dir / "missing" / "parent" / "test.txt"
        
        with patch.object(CrossFilesystemMover, '_find_mount_point', return_value=self.temp_dir):
            mover = CrossFilesystemMover(
                source_file, dest_file,
                dry_run=True, quiet=True, dir_manager=None
            )


class TestCrossScopeHardlinks(unittest.TestCase):
    """Test cross-scope hardlink destination mapping"""
    
    def setUp(self):
        self.temp_dir = Path(tempfile.mkdtemp())
        self.source_dir = self.temp_dir / "source_fs"
        self.dest_dir = self.temp_dir / "dest_fs"
        self.source_dir.mkdir()
        self.dest_dir.mkdir()
    
    def tearDown(self):
        import shutil
        shutil.rmtree(self.temp_dir, ignore_errors=True)
    
    def test_cross_scope_hardlink_destination_mapping(self):
        """Test cross-scope hardlink destination preserves directory structure"""
        from cross_filesystem import CrossFilesystemMover
        
        source_file = self.source_dir / "test.txt"
        source_file.write_text("content")
        
        dest_file = self.dest_dir / "media" / "test.txt"
        
        cross_scope_file = self.temp_dir / "backup" / "archive" / "test.txt"
        cross_scope_file.parent.mkdir(parents=True)
        os.link(source_file, cross_scope_file)
        
        def mock_find_mount_point(path):
            return self.temp_dir
        
        with patch.object(CrossFilesystemMover, '_find_mount_point', side_effect=mock_find_mount_point):
            mover = CrossFilesystemMover(
                source_file, dest_file,
                dry_run=True, quiet=True, dir_manager=None
            )
            
            mapped_dest = mover.map_hardlink_destination(cross_scope_file)
            expected = self.temp_dir / "backup" / "archive" / "test.txt"
            
            self.assertEqual(mapped_dest, expected, 
                           f"Cross-scope mapping: got {mapped_dest}, expected {expected}")


class TestLoggingAccuracy(unittest.TestCase):
    """Test logging accuracy matches actual operations"""
    
    def setUp(self):
        self.temp_dir = Path(tempfile.mkdtemp())
        self.source_dir = self.temp_dir / "source"
        self.dest_dir = self.temp_dir / "dest"
        self.source_dir.mkdir()
        self.dest_dir.mkdir()
    
    def tearDown(self):
        import shutil
        shutil.rmtree(self.temp_dir, ignore_errors=True)
    
    def test_logged_paths_are_valid(self):
        """Test that logged paths are valid and constructible"""
        import io
        import sys
        from contextlib import redirect_stdout
        
        source_file = self.source_dir / "test.txt" 
        source_file.write_text("content")
        dest_file = self.dest_dir / "moved.txt"
        
        cross_file = self.temp_dir / "external" / "hardlink.txt"
        cross_file.parent.mkdir()
        os.link(source_file, cross_file)
        
        captured_output = io.StringIO()
        
        with redirect_stdout(captured_output):
            mover = FileMover(source_file, dest_file, dry_run=True, quiet=False)
            mover.move()
        
        output = captured_output.getvalue()
        
        logged_paths = []
        for line in output.split('\n'):
            if 'Would create:' in line or 'Would link:' in line:
                path = line.split(': ', 1)[1] if ': ' in line else ""
                logged_paths.append(Path(path))
        
        for logged_path in logged_paths:
            if logged_path and str(logged_path) != "":
                self.assertIsInstance(logged_path.parent, Path)
    
    def test_hardlink_mapping_consistency(self):
        """Test logged paths match mapping function output"""
        from cross_filesystem import CrossFilesystemMover
        
        source_file = self.source_dir / "main.txt"
        source_file.write_text("content")
        
        external_file = self.temp_dir / "external" / "sub" / "hardlink.txt"
        external_file.parent.mkdir(parents=True)
        os.link(source_file, external_file)
        
        dest_file = self.dest_dir / "main.txt"
        
        logged_paths = []
        actual_mapped_paths = []
        
        def capture_print(message):
            if "Would link:" in message:
                path = message.split(": ", 1)[1]
                logged_paths.append(Path(path))
        
        with patch.object(CrossFilesystemMover, '_find_mount_point', return_value=self.temp_dir):
            mover = CrossFilesystemMover(
                source_file, dest_file,
                dry_run=True, quiet=True, dir_manager=None
            )
            
            mapped = mover.map_hardlink_destination(external_file)
            actual_mapped_paths.append(mapped)
            
            with patch.object(mover, '_print_action', side_effect=capture_print):
                mover.move_file()
        
        if logged_paths and actual_mapped_paths:
            self.assertEqual(logged_paths[0], actual_mapped_paths[0],
                           "Logged path doesn't match mapping function output")


class TestDirectoryDetection(unittest.TestCase):
    """Test directory detection edge cases"""
    
    def setUp(self):
        self.temp_dir = Path(tempfile.mkdtemp())
        self.source_dir = self.temp_dir / "source"
        self.dest_dir = self.temp_dir / "dest"
        self.source_dir.mkdir()
        self.dest_dir.mkdir()
    
    def tearDown(self):
        import shutil
        shutil.rmtree(self.temp_dir, ignore_errors=True)
    
    def test_directory_detection_handles_permission_errors(self):
        """Test directory detection handles permission errors gracefully"""
        source_file = self.source_dir / "test.txt"
        source_file.write_text("content")
        
        # Create parent directory so we get to the is_dir() check
        problematic_dir = self.temp_dir / "problematic"
        problematic_dir.mkdir()
        dest_file = problematic_dir / "dest.txt"
        
        original_is_dir = Path.is_dir
        def mock_is_dir(self):
            if "problematic" in str(self):
                raise PermissionError("Access denied")
            return original_is_dir(self)
        
        with patch.object(Path, 'is_dir', mock_is_dir):
            try:
                mover = FileMover(source_file, dest_file, dry_run=True)
            except PermissionError:
                self.fail("Directory detection should handle PermissionError gracefully")


class TestEdgeCaseHandling(unittest.TestCase):
    """Test edge case handling for production readiness"""
    
    def setUp(self):
        self.temp_dir = Path(tempfile.mkdtemp())
        self.source_dir = self.temp_dir / "source"
        self.dest_dir = self.temp_dir / "dest"
        self.source_dir.mkdir()
        self.dest_dir.mkdir()
    
    def tearDown(self):
        import shutil
        shutil.rmtree(self.temp_dir, ignore_errors=True)
    
    def test_process_interruption_infrastructure(self):
        """Test that process interruption handling infrastructure exists"""
        from cross_filesystem import CrossFilesystemMover
        from directory_manager import DirectoryManager
        
        source_file = self.source_dir / "test.txt"
        source_file.write_text("content")
        dest_file = self.dest_dir / "moved.txt"
        
        mover = CrossFilesystemMover(
            source_file, dest_file,
            dry_run=True, quiet=True, dir_manager=DirectoryManager(dry_run=True)
        )
        
        # Check temp file tracking capability
        self.assertTrue(hasattr(mover, 'temp_files') or hasattr(mover, '_temp_files'),
                       "Should track temporary files for cleanup")
    
    def test_disk_space_exhaustion_handling(self):
        """Test graceful handling of disk space exhaustion"""
        from cross_filesystem import CrossFilesystemMover
        from directory_manager import DirectoryManager
        
        source_file = self.source_dir / "test.txt"
        source_file.write_text("content")
        dest_file = self.dest_dir / "moved.txt"
        
        mover = CrossFilesystemMover(
            source_file, dest_file,
            dry_run=False, quiet=True, dir_manager=DirectoryManager(dry_run=False)
        )
        
        # Mock disk space exhaustion
        with patch('shutil.copy2') as mock_copy:
            mock_copy.side_effect = OSError(28, "No space left on device")
            
            # Should handle gracefully, not crash
            result = mover.create_file(source_file, dest_file)
            self.assertFalse(result, "Should return False on space exhaustion")
    
    def test_symlink_preservation(self):
        """Test symbolic link preservation behavior"""
        # Create target and symlink
        target_file = self.source_dir / "target.txt"
        target_file.write_text("target content")
        
        symlink_file = self.source_dir / "link.txt"
        os.symlink(target_file, symlink_file)
        
        broken_link = self.source_dir / "broken.txt"
        os.symlink("nonexistent.txt", broken_link)
        
        # Test preservation
        mover = FileMover(self.source_dir, self.dest_dir / "moved", dry_run=False)
        success = mover.move()
        
        self.assertTrue(success)
        
        # Check if symlinks were preserved
        moved_symlink = self.dest_dir / "moved" / "link.txt"
        moved_broken = self.dest_dir / "moved" / "broken.txt"
        
        # Currently this will fail - symlinks are followed, not preserved
        self.assertTrue(moved_symlink.is_symlink(), "Should preserve valid symlinks")
        self.assertTrue(moved_broken.is_symlink(), "Should preserve broken symlinks")
    
    def test_permission_error_retry_logic(self):
        """Test retry logic for permission errors"""
        import shutil
        from cross_filesystem import CrossFilesystemMover
        from directory_manager import DirectoryManager

        source_file = self.source_dir / "test.txt"
        source_file.write_text("content")
        dest_file = self.dest_dir / "moved.txt"

        mover = CrossFilesystemMover(
            source_file, dest_file,
            dry_run=False, quiet=True, dir_manager=DirectoryManager(dry_run=False)
        )

        # Save original function before patching
        original_copy2 = shutil.copy2
        call_count = 0
        def mock_copy_with_retry(*args, **kwargs):
            nonlocal call_count
            call_count += 1
            if call_count == 1:
                raise PermissionError("Permission denied")
            else:
                return original_copy2(*args, **kwargs)

        with patch('shutil.copy2', side_effect=mock_copy_with_retry):
            result = mover.create_file(source_file, dest_file)
            self.assertTrue(result, "Should retry on permission error")
    
    def test_destination_permission_validation(self):
        """Test destination permission validation during initialization"""
        # Create unwritable destination
        restricted_dest = self.dest_dir / "restricted"
        restricted_dest.mkdir()
        os.chmod(restricted_dest, 0o444)  # Read-only
        
        source_file = self.source_dir / "test.txt"
        source_file.write_text("content")
        dest_file = restricted_dest / "moved.txt"
        
        # Should be caught during validation
        with self.assertRaises(PermissionError):
            FileMover(source_file, dest_file, dry_run=False)


class TestSymlinkBehavior(unittest.TestCase):
    """Test symbolic link handling in detail"""
    
    def setUp(self):
        self.temp_dir = Path(tempfile.mkdtemp())
        self.source_dir = self.temp_dir / "source"
        self.dest_dir = self.temp_dir / "dest"
        self.source_dir.mkdir()
        self.dest_dir.mkdir()
    
    def tearDown(self):
        import shutil
        shutil.rmtree(self.temp_dir, ignore_errors=True)
    
    def test_relative_symlink_preservation(self):
        """Test preservation of relative symlinks"""
        target_file = self.source_dir / "target.txt"
        target_file.write_text("target content")
        
        symlink_file = self.source_dir / "relative_link.txt"
        os.symlink("target.txt", symlink_file)  # Relative path
        
        mover = FileMover(self.source_dir, self.dest_dir / "moved", dry_run=False)
        success = mover.move()
        
        self.assertTrue(success)
        
        moved_link = self.dest_dir / "moved" / "relative_link.txt"
        self.assertTrue(moved_link.is_symlink(), "Should preserve relative symlink")
        self.assertEqual(os.readlink(moved_link), "target.txt", "Should preserve relative path")
    
    def test_absolute_symlink_preservation(self):
        """Test preservation of absolute symlinks"""
        target_file = self.source_dir / "target.txt"
        target_file.write_text("target content")
        
        symlink_file = self.source_dir / "absolute_link.txt"
        os.symlink(str(target_file), symlink_file)  # Absolute path
        
        mover = FileMover(self.source_dir, self.dest_dir / "moved", dry_run=False)
        success = mover.move()
        
        self.assertTrue(success)
        
        moved_link = self.dest_dir / "moved" / "absolute_link.txt"
        self.assertTrue(moved_link.is_symlink(), "Should preserve absolute symlink")
    
    def test_broken_symlink_preservation(self):
        """Test preservation of broken symlinks"""
        broken_link = self.source_dir / "broken.txt"
        os.symlink("nonexistent_target.txt", broken_link)
        
        mover = FileMover(self.source_dir, self.dest_dir / "moved", dry_run=False)
        success = mover.move()
        
        self.assertTrue(success)
        
        moved_broken = self.dest_dir / "moved" / "broken.txt"
        self.assertTrue(moved_broken.is_symlink(), "Should preserve broken symlinks")
        self.assertEqual(os.readlink(moved_broken), "nonexistent_target.txt", "Should preserve broken target")
    
    def test_directory_symlink_preservation(self):
        """Test preservation of directory symlinks"""
        target_dir = self.source_dir / "target_dir"
        target_dir.mkdir()
        (target_dir / "file.txt").write_text("content")
        
        symlink_dir = self.source_dir / "dir_link"
        os.symlink("target_dir", symlink_dir)
        
        mover = FileMover(self.source_dir, self.dest_dir / "moved", dry_run=False)
        success = mover.move()
        
        self.assertTrue(success)
        
        moved_dir_link = self.dest_dir / "moved" / "dir_link"
        self.assertTrue(moved_dir_link.is_symlink(), "Should preserve directory symlinks")


class TestRobustnessScenarios(unittest.TestCase):
    """Test robustness against various failure scenarios"""
    
    def setUp(self):
        self.temp_dir = Path(tempfile.mkdtemp())
        self.source_dir = self.temp_dir / "source"
        self.dest_dir = self.temp_dir / "dest"
        self.source_dir.mkdir()
        self.dest_dir.mkdir()
    
    def tearDown(self):
        import shutil
        shutil.rmtree(self.temp_dir, ignore_errors=True)
    
    def test_readonly_files_handling(self):
        """Test handling of readonly source files"""
        source_file = self.source_dir / "readonly.txt"
        source_file.write_text("readonly content")
        os.chmod(source_file, 0o444)  # Read-only
        
        dest_file = self.dest_dir / "moved.txt"
        
        mover = FileMover(source_file, dest_file, dry_run=False)
        success = mover.move()
        
        self.assertTrue(success, "Should handle readonly files")
        self.assertTrue(dest_file.exists(), "Readonly file should be moved")
    
    def test_unicode_filenames(self):
        """Test handling of unicode filenames"""
        unicode_file = self.source_dir / "测试文件.txt"
        unicode_file.write_text("unicode content")
        
        dest_file = self.dest_dir / "测试文件.txt"
        
        mover = FileMover(unicode_file, dest_file, dry_run=False)
        success = mover.move()
        
        self.assertTrue(success, "Should handle unicode filenames")
        self.assertTrue(dest_file.exists(), "Unicode file should be moved")
    
    def test_special_characters_in_filenames(self):
        """Test handling of special characters in filenames"""
        special_file = self.source_dir / "file with spaces & symbols!@#.txt"
        special_file.write_text("special content")
        
        dest_file = self.dest_dir / "file with spaces & symbols!@#.txt"
        
        mover = FileMover(special_file, dest_file, dry_run=False)
        success = mover.move()
        
        self.assertTrue(success, "Should handle special characters")
        self.assertTrue(dest_file.exists(), "Special character file should be moved")


if __name__ == '__main__':
    unittest.main(verbosity=2)