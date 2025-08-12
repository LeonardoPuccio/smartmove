# SmartMove

Cross-filesystem file mover with hardlink preservation. Moves files and directories between different filesystems while maintaining hardlink relationships that would otherwise be broken by standard tools.

## Features

- **Hardlink preservation** within source filesystem across filesystem boundaries
- **Automatic detection** of same vs cross-filesystem moves
- **Memory-indexed scanning** using `find -xdev -inum` for fast hardlink detection
- **Dry-run mode** for safe preview of operations
- **Unix-style interface** similar to `mv` command
- **Proper ownership** and permission preservation
- **Empty directory cleanup** after successful moves

## Installation

First, clone the repository:
```bash
git clone https://github.com/LeonardoPuccio/smartmove.git
cd smartmove
```

Choose one installation method:

### Option 1: Symlink (Development/Temporary)
```bash
sudo ln -s $(pwd)/smartmove.py /usr/local/bin/smv
```
- **Keep source code** - deleting this directory breaks the command
- Easy to modify and develop
- Good for testing or development

### Option 2: Package Install (Permanent)
```bash
pip install .
```
- **Can delete source code** after installation
- Standard Python package installation
- More permanent solution
- To modify, reinstall with `pip install .`

Both create `smv` command globally

## Usage

```bash
# Basic syntax
smv SOURCE DEST [options]

# Examples
smv "/mnt/ssd/movie" "/mnt/hdd/movie" --dry-run
smv "/mnt/ssd/documents" "/mnt/hdd/backup/" -p
sudo smv "/mnt/fast/media" "/mnt/slow/archive" --verbose
```

**Options:**
- `-p, --parents` - Create parent directories as needed
- `--dry-run` - Preview actions only
- `--verbose` - Show detailed progress
- `--debug` - Enable debug logging (requires --verbose)
- `-q, --quiet` - Suppress output except errors

## Why SmartMove?

Standard tools like `rsync`, `cp`, and `mv` break hardlinks when moving across filesystems:

```bash
# Setup: Create hardlinked files across directories
mkdir -p /mnt/ssd2tb/test1 /mnt/ssd2tb/test2
echo "content" > /mnt/ssd2tb/test1/original.txt
ln /mnt/ssd2tb/test1/original.txt /mnt/ssd2tb/test2/hardlink.txt
stat -c "Links: %h" /mnt/ssd2tb/test1/original.txt  # Shows: Links: 2

# rsync breaks hardlinks when only transferring part of filesystem
rsync -aH --mkpath /mnt/ssd2tb/test1/ /mnt/hdd20tb/test1/
stat -c "Links: %h" /mnt/hdd20tb/test1/original.txt   # Shows: Links: 1 (hardlink broken!)

# Clean up rsync test
rm -rf /mnt/hdd20tb/test1 /mnt/hdd20tb/test2

# SmartMove preserves all hardlinks by scanning entire filesystem
smv /mnt/ssd2tb/test1 /mnt/hdd20tb/test1
stat -c "Links: %h" /mnt/hdd20tb/test2/hardlink.txt  # Shows: Links: 2 (both files moved)

# Final clean up test files
rm -rf /mnt/ssd2tb/test1 /mnt/ssd2tb/test2 /mnt/hdd20tb/test1 /mnt/hdd20tb/test2
```

**Root cause:** `rsync -H` only preserves hardlinks within the transferred file set, missing hardlinks outside the source directory.

### MergerFS Compatibility
SmartMove operates on underlying filesystems. File timestamps may change which version MergerFS displays, but hardlink preservation remains intact.

## Examples

```bash
# Single file with hardlinks
smv /mnt/ssd/file.txt /mnt/hdd/file.txt

# Directory with preview
smv "/mnt/ssd/media" "/mnt/hdd/backup/" --dry-run -p

# Large operation with progress
sudo smv /mnt/fast/dataset /mnt/slow/archive -p --verbose
```

## Current Limitations

- Searches hardlinks within source filesystem boundaries only
- Uses `find -xdev` for performance (stays within mount points)
- Cross-scope hardlinks outside source tree may not be detected in complex scenarios

**Planned:** Future versions will include comprehensive filesystem-wide detection options.

## Requirements

- Python 3.6+, Unix/Linux system
- Root privileges (for ownership preservation)
- No external dependencies

## Testing & Development

```bash
# Setup development environment
python3 -m venv .venv
source .venv/bin/activate  # Linux/Mac

pip install -r requirements-dev.txt

# Run tests
python3 -m pytest tests/test_unit.py tests/test_integration.py -v  # Fast tests
sudo .venv/bin/python3 -m pytest tests/test_e2e.py -v  # Real filesystem tests
```

### Test Types
- **Unit tests** (`test_unit.py`) - Fast, isolated component tests
- **Integration tests** (`test_integration.py`) - Component interaction tests
- **E2E tests** (`test_e2e.py`) - Real filesystem validation with loop devices

The virtual environment isolates project dependencies from your system Python, preventing conflicts.

## Contributing

Submit issues and pull requests on GitHub. Ensure all tests pass.

## License

MIT License - see LICENSE file for details.