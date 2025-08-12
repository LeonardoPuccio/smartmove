"""
Cross-Filesystem Mover

Handles cross-filesystem moves with hardlink preservation.
Optimized with mount point detection and memory index for hardlinks.
"""

import os
import shutil
import logging
import subprocess
from pathlib import Path
from datetime import datetime

logger = logging.getLogger(__name__)

class CrossFilesystemMover:
    """Handles cross-filesystem moves with hardlink preservation"""
    
    def __init__(self, source_path, dest_path, dry_run=False, quiet=False, dir_manager=None):
        self.source_path = source_path
        self.dest_path = dest_path
        self.dry_run = dry_run
        self.quiet = quiet
        self.dir_manager = dir_manager
        self.moved_inodes = set()
        self.inode_link_counts = {}
        self.source_root = self._find_mount_point(self.source_path)
        self.hardlink_index = None  # Built on first use
        
        logger.debug(f"Source mount point: {self.source_root}")
    
    def _print_action(self, message):
        """Print action with timestamp unless quiet mode"""
        if not self.quiet:
            timestamp = datetime.now().strftime('%Y-%m-%d %H:%M:%S,%f')[:-3]
            print(f"{timestamp} - {message}")
    
    def _find_mount_point(self, path):
        """Find mount point for given path"""
        path = os.path.realpath(path)
        while not os.path.ismount(path):
            parent = os.path.dirname(path)
            if parent == path:  # Reached root
                break
            path = parent
        return Path(path)
    
    def _build_hardlink_index(self):
        """Build memory index of all hardlinks in source filesystem"""
        if self.hardlink_index is not None:
            return  # Already built
        
        logger.debug(f"Building hardlink index for {self.source_root}")
        self.hardlink_index = {}
        
        try:
            # Single scan to find all hardlinked files
            result = subprocess.run(
                ['find', str(self.source_root), '-xdev', '-type', 'f', '-links', '+1', '-printf', '%i %p\n'],
                capture_output=True, text=True, timeout=300, check=False
            )
            
            if result.returncode == 0:
                for line in result.stdout.strip().split('\n'):
                    if not line.strip():
                        continue
                    
                    parts = line.strip().split(' ', 1)
                    if len(parts) == 2:
                        inode = int(parts[0])
                        file_path = Path(parts[1])
                        
                        if inode not in self.hardlink_index:
                            self.hardlink_index[inode] = []
                        self.hardlink_index[inode].append(file_path)
                
                hardlink_groups = len(self.hardlink_index)
                total_hardlinked_files = sum(len(paths) for paths in self.hardlink_index.values())
                logger.debug(f"Indexed {hardlink_groups} hardlink groups ({total_hardlinked_files} files)")
            else:
                logger.warning(f"Failed to build hardlink index: {result.stderr}")
                self.hardlink_index = {}
                
        except (subprocess.TimeoutExpired, OSError) as e:
            logger.warning(f"Could not build hardlink index: {e}")
            self.hardlink_index = {}

    def find_hardlinks(self, file_path):
        """Find all hardlinks using pre-built memory index"""
        try:
            file_stat = file_path.stat()
            
            if file_stat.st_nlink <= 1:
                return [file_path]
            
            # Build index on first use
            self._build_hardlink_index()
            
            # O(1) lookup from memory index
            inode = file_stat.st_ino
            hardlinks = self.hardlink_index.get(inode, [file_path])
            
            if len(hardlinks) > 1:
                logger.debug(f"Found {len(hardlinks)} hardlinks for inode {inode}")
            
            return hardlinks
            
        except (OSError, FileNotFoundError) as e:
            logger.debug(f"Hardlink detection failed for {file_path}: {e}")
            return [file_path]
    
    def map_hardlink_destination(self, source_hardlink):
        """Map hardlink destination path"""
        try:
            rel_path = source_hardlink.relative_to(self.source_path)
            return self.dest_path / rel_path
        except ValueError:
            return self.dest_path.parent / source_hardlink.name
    
    def create_file(self, source_file, dest_file):
        """Create file at destination via copy"""
        try:
            self.dir_manager.ensure_directory(dest_file.parent)
            
            if not self.dry_run:
                shutil.copy2(source_file, dest_file)
                # Preserve ownership and permissions
                source_stat = source_file.stat()
                os.chmod(dest_file, source_stat.st_mode)
                try:
                    os.chown(dest_file, source_stat.st_uid, source_stat.st_gid)
                except PermissionError:
                    logger.debug(f"Could not preserve ownership for {dest_file}")
            
            action = "Would create" if self.dry_run else "✓ Created"
            self._print_action(f"{action}: {dest_file}")
            return True
            
        except Exception as e:
            logger.error(f"Copy failed: {source_file} → {dest_file}: {e}")
            return False
    
    def create_hardlink(self, primary_dest_file, dest_hardlink, source_file):
        """Create hardlink to existing destination file"""
        try:
            self.dir_manager.ensure_directory(dest_hardlink.parent)
            
            if not self.dry_run:
                os.link(primary_dest_file, dest_hardlink)
            action = "Would link" if self.dry_run else "✓ Linked"
            self._print_action(f"{action}: {dest_hardlink}")
            return True
        except OSError as e:
            if e.errno == 18:  # Cross-device fallback
                logger.debug(f"Cross-device hardlink failed, copying {dest_hardlink.name}")
                return self.create_file(source_file, dest_hardlink)
            else:
                logger.error(f"Hardlink creation failed: {dest_hardlink}: {e}")
                return False
    
    def move_hardlink_group(self, source_file, dest_file):
        """Move file and recreate all its hardlinks at destination"""
        file_stat = source_file.stat()
        
        if file_stat.st_ino in self.moved_inodes:
            logger.debug(f"Skipping already processed inode {file_stat.st_ino}")
            return True

        self.inode_link_counts[file_stat.st_ino] = file_stat.st_nlink
        
        message = "Processing" if not self.dry_run else "Would process"
        logger.debug(f"{message}: {source_file}")
        hardlinks = self.find_hardlinks(source_file)
        
        if len(hardlinks) > 1:          
            # Create primary file
            if not self.create_file(source_file, dest_file):
                return False
            
            successful_links = [source_file]
            
            # Create hardlinks for other instances
            for hardlink in hardlinks:
                if hardlink != source_file:
                    dest_hardlink = self.map_hardlink_destination(hardlink)
                    
                    if self.create_hardlink(dest_file, dest_hardlink, hardlink):
                        successful_links.append(hardlink)
            
            # Remove originals after successful recreation
            if len(successful_links) == len(hardlinks):
                for link in successful_links:
                    if not self.dry_run:
                        link.unlink()
                    self._print_action(f"Would remove: {link}" if self.dry_run else f"✓ Removed: {link}")
                self.moved_inodes.add(file_stat.st_ino)
                return True
            else:
                logger.error(f"Incomplete hardlink recreation: {len(successful_links)}/{len(hardlinks)}")
                return False
        else:
            # Single file
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
        logger.info(f"Moving directory: {self.source_path} → {self.dest_path}")
        
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
        hardlink_groups = sum(1 for inode, count in self.inode_link_counts.items() if count > 1)
        message = "Directory completed" if not self.dry_run else "Preview completed"
        if hardlink_groups > 0:
            logger.info(f"{message}: {files_processed} files, {hardlink_groups} hardlink groups preserved")
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
                    action = "Would remove empty directory" if self.dry_run else "✓ Removed empty directory"
                    self._print_action(f"{action}: {root_path}")
        except OSError as e:
            logger.debug(f"Directory cleanup issue: {e}")