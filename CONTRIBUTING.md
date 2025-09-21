# Contributing to SmartMove

## Development Setup

```bash
# Setup environment
python3 -m venv .venv
source .venv/bin/activate
make install-dev

# Install globally for sudo access
pipx install -e .
sudo ln -sf ~/.local/bin/smv /usr/local/bin/smv
```

The editable install (`-e`) ensures code changes take effect immediately without reinstalling.

## Development Workflow

```bash
make fix     # Auto-fix formatting and linting issues
make test    # Run all tests with coverage
make lint    # Verify code compliance
```

## Testing

### Test Types
- **Unit tests** (`test_unit.py`) - Fast, isolated component tests
- **Integration tests** (`test_integration.py`) - Component interaction tests  
- **CLI tests** (`test_cli.py`) - Command-line interface tests
- **E2E tests** (`test_e2e.py`) - Real filesystem validation with loop devices

### Running Tests

```bash
# Quick development tests (no coverage)
make test-quick

# Full test suite with coverage
make test

# Individual test types
make test-unit          # Unit + CLI tests
make test-integration   # Integration tests  
sudo make test-e2e      # E2E tests (requires root)
sudo make test-performance  # Large-scale performance tests
```

### E2E Test Requirements
- Root privileges for loop device creation
- 2GB+ free disk space for filesystem tests
- Modern CPU (may take minutes on limited hardware)

Large-scale performance tests:
```bash
sudo RUN_LARGE_SCALE_TESTS=1 .venv/bin/python3 -m pytest tests/test_e2e.py -v
```

## Code Quality

- **Formatting**: Black + isort
- **Linting**: Ruff + Black compliance checks
- **Coverage**: Minimum 80% line coverage, aiming for 90%+
- **Pre-commit**: Automatic formatting and linting on commit

## Architecture

```
smartmove/
├── cli.py              # Command-line interface
├── core/
│   ├── mover.py        # Main FileMover orchestrator
│   └── filesystem.py   # Cross-filesystem operations
└── utils/
    ├── progress.py     # Progress reporting with Unicode/ASCII fallback
    └── directory.py    # Directory management utilities
```

## Commit Guidelines

Follow [Conventional Commits](https://www.conventionalcommits.org/) format:

```
feat: add progress reporting with Unicode/ASCII fallback
fix: resolve hardlink detection race condition  
docs: update installation instructions
test: add coverage for edge cases
refactor: split cross_filesystem into separate modules
```

## Performance Considerations

- **Memory indexing**: Use `find` command for hardlink detection
- **Progress updates**: Throttle to every 10 files to avoid output flooding
- **Filesystem operations**: Atomic moves with temp file cleanup
- **Cross-device fallbacks**: Handle EXDEV errors gracefully

## Debugging

Enable debug logging:
```bash
sudo smv source dest --verbose --debug
```

Common debug scenarios:
- Hardlink detection failures
- Permission errors during atomic operations  
- Cross-filesystem mount point detection
- Unicode terminal detection issues