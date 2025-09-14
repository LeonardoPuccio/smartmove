# SmartMove Demo

Interactive demonstration showing SmartMove's superior hardlink preservation vs traditional tools.

## Quick Start

```bash
chmod +x same_fs_demo.sh
./same_fs_demo.sh
```

## What it demonstrates

**Scenario:** File hardlinked across directories, moving only one directory

- **TAR/CPIO:** Break hardlinks completely
- **RSYNC:** Orphan external hardlinked files  
- **SmartMove:** Preserve all hardlinks by scanning entire filesystem

## Online Demo

[![Open in GitHub Codespaces](https://github.com/codespaces/badge.svg)](https://codespaces.new/LeonardoPuccio/smartmove)

Click above for one-click demo environment in your browser.

## Output Example

```
==== TESTING RSYNC ====
Orphaned file (external.txt, hardlink lost)

==== TESTING SMARTMOVE ====
Hardlink preserved
```

SmartMove finds hardlinks everywhere, not just in moved directory.