# SmartMove [![Quality Gate Status](https://sonarcloud.io/api/project_badges/measure?project=smartmove&metric=alert_status)](https://sonarcloud.io/summary/new_code?id=smartmove) [![Coverage](https://sonarcloud.io/api/project_badges/measure?project=smartmove&metric=coverage)](https://sonarcloud.io/summary/new_code?id=smartmove)

Cross-filesystem file mover with hardlink preservation. Moves files and directories between different filesystems while maintaining hardlink relationships that would otherwise be broken by standard tools.

## Features

- **Dual hardlink preservation** - solves cross-scope and cross-filesystem hardlink breakage
- **Progress reporting** with Unicode/ASCII fallback, rate display, and ETA
- **Automatic detection** of same vs cross-filesystem moves
- **Memory-indexed scanning** using `find -xdev` for fast hardlink detection
- **Dry-run mode** for safe preview of operations
- **Unix-style interface** similar to `mv` command
- **Proper ownership** and permission preservation
- **Empty directory cleanup** after successful moves

## Installation

```bash
pipx install git+https://github.com/LeonardoPuccio/smartmove.git
sudo ln -sf ~/.local/bin/smv /usr/local/bin/smv
```

The symlink ensures `sudo` can access the command while keeping the package isolated.

## Usage

```bash
# Basic syntax
sudo smv SOURCE DEST [options]

# Examples  
sudo smv "/mnt/ssd/movie" "/mnt/hdd/movie" --dry-run
sudo smv "/mnt/ssd/documents" "/mnt/hdd/backup/" -p
sudo smv "/mnt/fast/media" "/mnt/slow/archive" --verbose
sudo smv "/mnt/mergefs/dataset" "/mnt/archive" --comprehensive --verbose
```

**Options:**
- `-p, --parents` - Create parent directories as needed
- `--dry-run` - Preview actions only
- `--comprehensive` - Scan all mounted filesystems for hardlinks (slower)
- `-v, --verbose` - Show detailed progress messages
- `--debug` - Enable debug logging (requires --verbose)
- `-q, --quiet` - Suppress output except errors
- `--no-progress` - Disable progress display
- `--version` - Show version information

## Progress Display

SmartMove shows progress for directory operations:

```bash
# Default: Progress bar with Unicode support
[████████████░░░░░░░░] 60% 1,200/2,000 1.2k/s ETA 0:45

# ASCII fallback for basic terminals
[============>       ] 60% 1,200/2,000 1.2k/s ETA 0:45
```

Progress respects verbosity settings:
- Default: Progress bar only
- `--verbose`: Progress bar + detailed logs  
- `--verbose --no-progress`: Detailed logs only
- `--quiet`: Silent operation

## Why SmartMove?

SmartMove solves **two critical hardlink problems** that standard tools can't handle:

### Problem 1: Cross-Scope Hardlinks (Same Filesystem)
```bash
# Setup: hardlinks span directories
mkdir -p /tmp/source/{downloads,media} /tmp/dest
echo "content" > /tmp/source/downloads/file.txt
ln /tmp/source/downloads/file.txt /tmp/source/media/hardlink.txt
stat -c "Links: %h" /tmp/source/downloads/file.txt  # Shows: Links: 2

# rsync only moves specified directory, breaks hardlinks
rsync -aH /tmp/source/media/ /tmp/dest/media/
stat -c "Links: %h" /tmp/dest/media/hardlink.txt     # Shows: Links: 1 (broken!)
# Original file orphaned in /tmp/source/downloads/

# SmartMove scans entire filesystem, preserves all hardlinks
sudo smv /tmp/source/media /tmp/dest/media
stat -c "Links: %h" /tmp/dest/downloads/file.txt     # Shows: Links: 2 (preserved!)
```

### Problem 2: Cross-Filesystem Hardlinks
```bash
# mv breaks hardlinks when crossing filesystem boundaries
mv /mnt/ssd/files /mnt/hdd/files  # Hardlinks become separate copies

# SmartMove preserves hardlinks across filesystem boundaries
sudo smv /mnt/ssd/files /mnt/hdd/files  # Hardlinks maintained
```

**Root cause:** Standard tools either ignore hardlinks outside the moved directory or break them when crossing filesystems. Even `rsync -H` only preserves hardlinks within the transferred file set, missing cross-scope hardlinks.

### Scanning Modes

**Default (optimized):** Fast scanning within source mount boundaries using `find -xdev`
- Optimal for typical single-drive to single-drive moves
- Uses `find -xdev` for performance  
- Covers 90%+ of use cases

**Comprehensive (`--comprehensive`):** Scans all mounted filesystems
- Required for complex storage setups (e.g., MergerFS pools)
- Finds hardlinks across multiple drives/storage devices
- Slower but complete detection

### MergerFS Compatibility
SmartMove operates on underlying filesystems. File timestamps may change which version MergerFS displays, but hardlink preservation remains intact. Use `--comprehensive` for complex storage pools or multi-drive setups.

## Requirements

- Python 3.10+, Unix/Linux system
- Root privileges (for ownership preservation)
- No external dependencies

## Development

See [CONTRIBUTING.md](CONTRIBUTING.md) for development setup, testing, and contribution guidelines.

## License

MIT License - see LICENSE file for details.