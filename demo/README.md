# SmartMove Demo

Interactive demonstration showing SmartMove's superior hardlink preservation vs traditional tools.

## Quick Start

```bash
chmod +x demo/same_fs_demo.sh
./demo/same_fs_demo.sh
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

Running:
  rsync -aH --remove-source-files "/tmp/demo_1202192/source/subfolder/" "/tmp/demo_1202192/dest/subfolder/"

SOURCE (/tmp):
  /tmp/demo_1202192/source/external.txt                        (inode:3422263    links:1)
DEST (/tmp):
  /tmp/demo_1202192/dest/subfolder/internal.txt                (inode:3422265    links:1)

[RESULT] RSYNC → Orphaned file (external.txt, hardlink lost)

==== TESTING SMARTMOVE ====

Running:
  sudo smv "/tmp/demo_1202192/source/subfolder" "/tmp/demo_1202192/dest/subfolder" -p --quiet

SOURCE (/tmp):
  /tmp/demo_1202192/source/external.txt                        (inode:3422263    links:2)
DEST (/tmp):
  /tmp/demo_1202192/dest/subfolder/internal.txt                (inode:3422263    links:2)

[RESULT] SMARTMOVE → Hardlink preserved
```

SmartMove finds hardlinks everywhere, not just in moved directory.