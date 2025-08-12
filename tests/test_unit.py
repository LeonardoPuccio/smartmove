#!/usr/bin/env python3
"""
Unit tests for SmartMove components
Updated with new optimizations (mount point detection, memory index)
"""

import os
import shutil
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch, MagicMock

from directory_manager import DirectoryManager
from cross_filesystem import CrossFilesystemMover


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
        self.assertIn(test_path, self.dir_manager.created_dirs, "Path should be cached after creation")
        
        # Second call should use cache
        with patch('pathlib.Path.mkdir') as mock_mkdir:
            self.dir_manager.ensure_directory(test_path)
            mock_mkdir.assert_not_called()
    
    def test_dry_run_mode(self):
        """Test that dry-run mode prevents actual directory creation"""
        dry_manager = DirectoryManager(dry_run=True)
        test_path = self.temp_dir / "dry_run_test"
        
        dry_manager.ensure_directory(test_path)
        self.assertFalse(test_path.exists(), "Directory should not be created in dry-run mode")
        self.assertIn(test_path, dry_manager.created_dirs, "Path should still be cached in dry-run mode")


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
            self.source_dir, self.dest_dir, 
            dry_run=True, quiet=True, dir_manager=self.dir_manager
        )
    
    def test_mount_point_detection(self):
        """Test mount point detection using os.path.ismount"""
        # Test with mock mount point
        with patch('os.path.ismount') as mock_ismount:
            # Simulate mount point at /mnt/test
            def ismount_side_effect(path):
                return str(path) == '/mnt/test'
            
            mock_ismount.side_effect = ismount_side_effect
            
            with patch('os.path.realpath', return_value='/mnt/test/deep/nested/file.txt'):
                mount_point = self.mover._find_mount_point(Path('/mnt/test/deep/nested/file.txt'))
                self.assertEqual(mount_point, Path('/mnt/test'))
    
    def test_mount_point_detection_root_fallback(self):
        """Test mount point detection falls back to root"""
        with patch('os.path.ismount', return_value=False):
            with patch('os.path.realpath', return_value='/some/path'):
                mount_point = self.mover._find_mount_point(Path('/some/path'))
                self.assertEqual(mount_point, Path('/'))
    
    def test_hardlink_index_building(self):
        """Test memory index building for hardlinks"""
        # Mock subprocess.run to simulate find command output
        mock_output = "12345 /path/to/file1.txt\n12345 /path/to/file2.txt\n67890 /path/to/file3.txt\n"
        
        with patch('subprocess.run') as mock_run:
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
        with patch('subprocess.run') as mock_run:
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
        self.assertEqual(hardlinks[0], single_file, "Returned file should be the original")
    
    def test_find_hardlinks_with_index(self):
        """Test hardlink detection using memory index"""
        test_file = self.source_dir / "test.txt"
        test_file.write_text("test content")
        
        # Mock os.stat instead of Path.stat
        with patch('os.stat') as mock_stat:
            # Create mock stat result
            mock_stat_result = type('MockStat', (), {
                'st_nlink': 3,
                'st_ino': 12345
            })()
            mock_stat.return_value = mock_stat_result
            
            # Pre-populate index
            self.mover.hardlink_index = {
                12345: [
                    Path("/path/to/file1.txt"),
                    Path("/path/to/file2.txt"), 
                    Path("/path/to/file3.txt")
                ]
            }
            
            hardlinks = self.mover.find_hardlinks(test_file)
            
            self.assertEqual(len(hardlinks), 3, "Should return all hardlinks from index")
    
    def test_find_hardlinks_builds_index_on_demand(self):
        """Test that index is built when first needed"""
        test_file = self.source_dir / "test.txt"
        test_file.write_text("test content")
        
        # Ensure index starts as None
        self.mover.hardlink_index = None
        
        # Mock os.stat to simulate multiple links
        with patch('os.stat') as mock_stat:
            mock_stat_result = type('MockStat', (), {
                'st_nlink': 2,
                'st_ino': 12345
            })()
            mock_stat.return_value = mock_stat_result
            
            # Mock _build_hardlink_index to set up empty index
            def mock_build_index():
                self.mover.hardlink_index = {}
            
            with patch.object(self.mover, '_build_hardlink_index', side_effect=mock_build_index) as mock_build:
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
        
        expected_dest = self.dest_dir.parent / "file.txt"
        self.assertEqual(mapped_dest, expected_dest)
    
    def test_create_file_preserves_stats(self):
        """Test that file creation preserves ownership and permissions"""
        source_file = self.source_dir / "test.txt"
        source_file.write_text("test content")
        dest_file = self.dest_dir / "copied.txt"
        
        # Test in non-dry-run mode
        real_mover = CrossFilesystemMover(
            self.source_dir, self.dest_dir, 
            dry_run=False, quiet=True, dir_manager=DirectoryManager(dry_run=False)
        )
        
        with patch('shutil.copy2') as mock_copy:
            with patch('os.chmod') as mock_chmod:
                with patch('os.chown') as mock_chown:
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
            self.source_dir, self.dest_dir, 
            dry_run=False, quiet=True, dir_manager=DirectoryManager(dry_run=False)
        )
        
        # Mock os.link to raise cross-device error
        with patch('os.link', side_effect=OSError(18, "Cross-device link")):
            with patch.object(real_mover, 'create_file', return_value=True) as mock_create:
                success = real_mover.create_hardlink(primary_file, dest_link, source_file)
                
                self.assertTrue(success)
                mock_create.assert_called_once_with(source_file, dest_link)
    
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
        self.assertFalse(dest_file.exists(), "Destination file should not be created in dry-run")


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
            return type("Stat", (), {"st_dev": dev_ids[min(call_count, len(dev_ids)-1)]})()
        return side_effect
    
    def test_same_filesystem_detection(self):
        """Test detection of same filesystem using device IDs"""
        from file_mover import FileMover
        
        source_file = self.temp_dir / "source.txt"
        dest_file = self.temp_dir / "dest.txt"
        source_file.write_text("test")
        
        with patch('pathlib.Path.stat', side_effect=self.make_stat_side_effect([123])):
            mover = FileMover(source_file, dest_file, dry_run=True)
            result = mover._detect_same_filesystem()
            
            self.assertTrue(result, "Same device IDs should be detected as same filesystem")
    
    def test_different_filesystem_detection(self):
        """Test detection of different filesystems using device IDs"""
        from file_mover import FileMover
        
        source_file = self.temp_dir / "source.txt"
        dest_file = self.temp_dir / "dest.txt"
        source_file.write_text("test")
        
        # First create mover to get through initialization
        mover = FileMover(source_file, dest_file, dry_run=True)
        
        # Now mock stat for the actual detection call
        with patch('pathlib.Path.stat', side_effect=self.make_stat_side_effect([123, 456])):
            result = mover._detect_same_filesystem()
            
            self.assertFalse(result, "Different device IDs should be detected as different filesystems")


class TestPerformanceOptimizations(unittest.TestCase):
    """Test performance optimizations"""
    
    def test_memory_index_vs_repeated_find(self):
        """Test that memory index avoids repeated subprocess calls"""
        temp_dir = Path(tempfile.mkdtemp())
        try:
            mover = CrossFilesystemMover(
                temp_dir / "source", temp_dir / "dest",
                dry_run=True, quiet=True
            )
            
            # Mock subprocess to count calls
            with patch('subprocess.run') as mock_run:
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
                self.assertEqual(first_call_count, second_call_count,
                               "Second call should use cached index, not make new subprocess call")
        finally:
            shutil.rmtree(temp_dir, ignore_errors=True)


if __name__ == '__main__':
    unittest.main()