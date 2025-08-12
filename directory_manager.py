"""
Directory Manager for Smart Move

Directory creation and caching to avoid redundant operations.
"""

import os
from pathlib import Path

class DirectoryManager:
    """Directory creation and caching to avoid redundant operations"""
    
    def __init__(self, dry_run=False):
        self.dry_run = dry_run
        self.created_dirs = set()
    
    def ensure_directory(self, path):
        """Ensure directory exists with caching to avoid redundant operations"""
        path = Path(path)
        if path in self.created_dirs or path.exists():
            return
        
        if not self.dry_run:
            path.mkdir(parents=True, exist_ok=True)
            # Preserve original user ownership for directories
            try:
                original_uid = int(os.environ.get('SUDO_UID', os.getuid()))
                original_gid = int(os.environ.get('SUDO_GID', os.getgid()))
                os.chown(path, original_uid, original_gid)
            except (ValueError, PermissionError):
                pass
            
        self.created_dirs.add(path)