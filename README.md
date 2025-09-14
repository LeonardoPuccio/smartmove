# SmartMove [![Quality Gate Status](https://sonarcloud.io/api/project_badges/measure?project=smartmove&metric=alert_status)](https://sonarcloud.io/summary/new_code?id=smartmove) [![Coverage](https://sonarcloud.io/api/project_badges/measure?project=smartmove&metric=coverage)](https://sonarcloud.io/summary/new_code?id=smartmove)

Cross-filesystem file mover with hardlink preservation. Moves files and directories between different filesystems while maintaining hardlink relationships that would otherwise be broken by standard tools.

## Features

- **Hardlink preservation** within source filesystem across filesystem boundaries
- **Automatic detection** of same vs cross-filesystem moves
- **Memory-indexed scanning** using `find -xdev` for fast hardlink detection
- **Dry-run mode** for safe preview of operations
- **Unix-style interface** similar to `mv` command
- **Proper ownership** and permission preservation
- **Empty directory cleanup** after successful moves

## Installation

Clone the repository:
```bash
git clone https://github.com/LeonardoPuccio/smartmove.git
cd smartmove
```

Choose one installation method:

### Option 1: Symlink (Development/Temporary)
```bash
chmod +x smartmove.py
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
sudo smv "/mnt/ssd/movie" "/mnt/hdd/movie" --dry-run
sudo smv "/mnt/ssd/documents" "/mnt/hdd/backup/" -p
sudo smv "/mnt/fast/media" "/mnt/slow/archive" --verbose
sudo smv "/mnt/mergefs/dataset" "/mnt/archive" --comprehensive --verbose
```

**Options:**
- `-p, --parents` - Create parent directories as needed
- `--dry-run` - Preview actions only
- `--comprehensive` - Scan all mounted filesystems for hardlinks (slower, for complex storage setups)
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
sudo rm -rf /mnt/hdd20tb/test1 /mnt/hdd20tb/test2

# SmartMove preserves all hardlinks by scanning source filesystem
sudo smv /mnt/ssd2tb/test1 /mnt/hdd20tb/test1
stat -c "Links: %h" /mnt/hdd20tb/test2/hardlink.txt  # Shows: Links: 2 (both files moved)

# Final clean up test files  
sudo rm -rf /mnt/ssd2tb/test1 /mnt/ssd2tb/test2 /mnt/hdd20tb/test1 /mnt/hdd20tb/test2
```

**Root cause:** `rsync -H` only preserves hardlinks within the transferred file set, missing hardlinks outside the source directory.

### Scanning Modes

**Default (source-filesystem-only):** Fast scanning within source mount boundaries
- Optimal for typical single-drive to single-drive moves
- Uses `find -xdev` for performance
- Covers 90%+ of use cases

**Comprehensive mode (`--comprehensive`):** Scans all mounted filesystems
- Required for complex storage setups (e.g., MergerFS pools)
- Finds hardlinks across multiple drives/storage devices
- Slower but complete detection

### MergerFS Compatibility
SmartMove operates on underlying filesystems. File timestamps may change which version MergerFS displays, but hardlink preservation remains intact. Use `--comprehensive` for complex storage pools or multi-drive setups.

## Examples

```bash
# Single file with hardlinks
smv /mnt/ssd/file.txt /mnt/hdd/file.txt

# Directory with preview
smv "/mnt/ssd/media" "/mnt/hdd/backup/" --dry-run -p

# Large operation with progress
sudo smv /mnt/fast/dataset /mnt/slow/archive -p --verbose

# Complex storage setup
sudo smv /mnt/mergefs/dataset /mnt/archive --comprehensive --verbose
```

## Requirements

- Python 3.6+, Unix/Linux system
- Root privileges (for ownership preservation)
- No external dependencies

## Testing & Development

### Development Workflow
```bash
# Setup
python3 -m venv .venv
source .venv/bin/activate  # Linux/Mac
make install-dev

# Local development cycle
make fix     # Auto-fix formatting and linting issues
make test    # Run all tests with coverage
make lint    # Verify code compliance
```

### Manual Testing
```bash
# Fast tests (unit + integration)
python3 -m pytest tests/test_unit.py tests/test_integration.py -v --cov=. --cov-report=xml

# E2E tests (require root for loop devices)  
sudo .venv/bin/python3 -m pytest tests/test_e2e.py -v
```

### E2E Test Performance
E2E tests complete in seconds due to:
- Small loop device filesystems (50MB for standard tests, 4GB for large-scale)
- Minimal test file sets (standard tests use <1,000 files)
- Optimized sparse file allocation

Large-scale tests available via:
```bash
sudo RUN_LARGE_SCALE_TESTS=1 .venv/bin/python3 -m pytest tests/test_e2e.py -v  # For performance testing
```

**System Requirements for Large-Scale Tests:**
- 8GB+ RAM (for filesystem operations)
- 5GB+ free disk space
- Modern CPU (may take several minutes on limited hardware)
- Not recommended for Raspberry Pi or similar constrained systems

### Test Types
- **Unit tests** (`test_unit.py`) - Fast, isolated component tests
- **Integration tests** (`test_integration.py`) - Component interaction tests
- **E2E tests** (`test_e2e.py`) - Real filesystem validation with loop devices

The virtual environment isolates project dependencies from your system Python, preventing conflicts.

## Contributing

Submit issues and pull requests on GitHub. Ensure all tests pass.

## License

MIT License - see LICENSE file for details.