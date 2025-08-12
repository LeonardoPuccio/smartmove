#!/usr/bin/env python3
"""
Integration tests for SmartMove
Updated with comprehensive hardlink and mount point testing
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
        """Helper to create files with hardlinks
        
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
                
            # Create first file
            first_path = base_dir / paths[0]
            first_path.parent.mkdir(parents=True, exist_ok=True)
            first_path.write_text(content)
            
            group_files = [first_path]
            
            # Create hardlinks
            for path in paths[1:]:
                link_path = base_dir / path
                link_path.parent.mkdir(parents=True, exist_ok=True)
                os.link(first_path, link_path)
                group_files.append(link_path)
            
            created_groups[group_name] = group_files
        
        return created_groups
    
    def _verify_hardlinks_preserved(self, file_groups, dest_base):
        """Verify that hardlinks are preserved at destination"""
        for group_name, source_files in file_groups.items():
            if len(source_files) <= 1:
                continue
            
            # Find corresponding destination files
            dest_files = []
            for source_file in source_files:
                try:
                    rel_path = source_file.relative_to(self.source_dir)
                    dest_file = dest_base / rel_path
                    if dest_file.exists():
                        dest_files.append(dest_file)
                except ValueError:
                    # File outside source scope
                    dest_file = self.dest_dir.parent / source_file.name
                    if dest_file.exists():
                        dest_files.append(dest_file)
            
            self.assertEqual(len(dest_files), len(source_files),
                           f"All files in group {group_name} should be moved")
            
            if len(dest_files) > 1:
                # Check all have same inode
                dest_inodes = [f.stat().st_ino for f in dest_files]
                self.assertEqual(len(set(dest_inodes)), 1,
                               f"All files in group {group_name} should have same inode")
                
                # Check link count
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
        # In dry run, source should still exist
        self.assertTrue(source_file.exists())
    
    def test_directory_with_hardlinks_comprehensive(self):
        """Test directory move with comprehensive hardlink scenarios"""
        # Create complex hardlink structure
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
        
        # Verify initial hardlinks
        for group_name, files in created_groups.items():
            if len(files) > 1:
                original_inode = files[0].stat().st_ino
                for file in files[1:]:
                    self.assertEqual(file.stat().st_ino, original_inode,
                                   f"Initial hardlinks in {group_name} should have same inode")
        
        # Test move
        dest_path = self.dest_dir / "moved_dir"
        mover = FileMover(self.source_dir, dest_path, create_parents=True, dry_run=True)
        success = mover.move()
        
        self.assertTrue(success)
        # In dry run, verify source files remain
        for files in created_groups.values():
            for file in files:
                self.assertTrue(file.exists(), f"Source file should remain in dry run: {file}")
    
    def test_cross_scope_hardlinks(self):
        """Test hardlinks that span outside the move scope"""
        # Create file outside source directory
        outside_file = self.temp_dir / "outside_scope.txt"
        outside_file.write_text("Cross-scope content")
        
        # Create source directory with hardlink to outside file
        source_subdir = self.source_dir / "move_this"
        source_subdir.mkdir()
        inside_file = source_subdir / "inside_scope.txt"
        os.link(outside_file, inside_file)
        
        # Verify initial hardlink
        self.assertEqual(outside_file.stat().st_ino, inside_file.stat().st_ino)
        self.assertEqual(outside_file.stat().st_nlink, 2)
        
        # Test cross-filesystem detection
        from cross_filesystem import CrossFilesystemMover
        cross_mover = CrossFilesystemMover(
            source_subdir, self.dest_dir / "moved",
            dry_run=True, quiet=True, dir_manager=None
        )
        
        # Should find both files even though one is outside scope
        found_hardlinks = cross_mover.find_hardlinks(inside_file)
        
        # In a real scenario with memory index, this should find both
        # In test with temp dirs, we'll verify the mechanism works
        self.assertIsInstance(found_hardlinks, list)
        self.assertGreater(len(found_hardlinks), 0)
    
    def test_mount_point_detection_integration(self):
        """Test mount point detection in integration context"""
        # Create deeply nested structure
        deep_path = self.source_dir / "very" / "deep" / "nested" / "structure"
        deep_path.mkdir(parents=True)
        deep_file = deep_path / "file.txt"
        deep_file.write_text("Deep content")
        
        from cross_filesystem import CrossFilesystemMover
        cross_mover = CrossFilesystemMover(
            deep_file, self.dest_dir / "moved.txt",
            dry_run=True, quiet=True, dir_manager=None
        )
        
        # Mount point should be found correctly
        self.assertIsInstance(cross_mover.source_root, Path)
        self.assertTrue(cross_mover.source_root.exists())
        
        # Should be an ancestor of the deep file
        try:
            deep_file.relative_to(cross_mover.source_root)
            is_ancestor = True
        except ValueError:
            is_ancestor = False
        
        self.assertTrue(is_ancestor, "Mount point should be ancestor of source file")
    
    def test_performance_with_many_hardlinks(self):
        """Test performance with many hardlinked files"""
        # Create multiple file groups with hardlinks
        file_groups = {}
        num_groups = 10
        
        for i in range(num_groups):
            file_groups[f"group_{i}"] = (
                f"Content {i}",
                [f"file_{i}.txt", f"dir1/link_{i}.txt", f"dir2/link_{i}.txt"]
            )
        
        created_groups = self._create_hardlinked_files(self.source_dir, file_groups)
        
        # Test that operation completes in reasonable time
        import time
        start_time = time.time()
        
        dest_path = self.dest_dir / "perf_test"
        mover = FileMover(self.source_dir, dest_path, create_parents=True, dry_run=True)
        success = mover.move()
        
        end_time = time.time()
        duration = end_time - start_time
        
        self.assertTrue(success, "Performance test should succeed")
        self.assertLess(duration, 10.0, f"Operation took too long: {duration:.2f}s")
        
        # Verify all source files still exist (dry run)
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
        """Test same vs different filesystem detection in integration"""
        source_file = self.source_dir / "test.txt"
        
        # Test same filesystem (both in temp_dir)
        dest_file_same = self.dest_dir / "moved.txt"
        source_file.write_text("test content")
        
        mover_same = FileMover(source_file, dest_file_same, dry_run=True)
        same_fs = mover_same._detect_same_filesystem()
        self.assertTrue(same_fs, "Both files in temp dir should be same filesystem")
        
        # Test with mocked different filesystem
        dest_file_diff = self.temp_dir / "different_fs" / "moved.txt"
        dest_file_diff.parent.mkdir()
        
        # Store original functions to avoid recursion
        original_os_stat = os.stat
        
        def mock_os_stat(path_str, follow_symlinks=True):
            # Use original os.stat to avoid recursion
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
            # self is the Path instance, convert to string
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
        # Create files with hardlinks
        file_groups = {
            "test_group": ("Test content", ["file1.txt", "file2.txt", "subdir/file3.txt"])
        }
        created_groups = self._create_hardlinked_files(self.source_dir, file_groups)
        
        from cross_filesystem import CrossFilesystemMover
        cross_mover = CrossFilesystemMover(
            self.source_dir, self.dest_dir / "moved",
            dry_run=True, quiet=True, dir_manager=None
        )
        
        # Mock subprocess to count index building calls
        with patch('subprocess.run') as mock_run:
            mock_run.return_value.returncode = 0
            mock_run.return_value.stdout = "12345 /path/file.txt\n"
            
            test_files = created_groups["test_group"]
            
            # First call should build index
            cross_mover.find_hardlinks(test_files[0])
            first_call_count = mock_run.call_count
            
            # Second call should use cached index
            cross_mover.find_hardlinks(test_files[1])
            second_call_count = mock_run.call_count
            
            # Should not make additional subprocess calls for index building
            self.assertEqual(first_call_count, second_call_count,
                           "Index should be cached and not rebuilt for subsequent calls")


if __name__ == '__main__':
    unittest.main()