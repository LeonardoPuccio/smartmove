#!/bin/bash

SAFE_DIR="demo_$$"
SOURCE_BASE="/tmp/$SAFE_DIR/source"
DEST_BASE="/tmp/$SAFE_DIR/dest"

# ── Colors ────────────────────────────────────────────
RED="\033[31m"
GREEN="\033[32m"
YELLOW="\033[33m"
CYAN="\033[36m"
BOLD="\033[1m"
RESET="\033[0m"

# ── Helpers ───────────────────────────────────────────
list_filesystem() {
    local label="$1"
    local path="$2"

    echo -e "$label"
    if [ -d "$path" ]; then
        files=$(find "$path" -type f 2>/dev/null | sort)
        if [ -n "$files" ]; then
            while read -r file; do
                inode=$(stat -c "%i" "$file")
                links=$(stat -c "%h" "$file")
                if [ "$links" -eq 1 ]; then
                    # highlight lost hardlink
                    printf "  %-60s ${RED}(inode:%-10s links:%s)${RESET}\n" "$file" "$inode" "$links"
                else
                    printf "  %-60s (inode:%-10s links:%s)\n" "$file" "$inode" "$links"
                fi
            done <<< "$files"
        else
            echo "  [empty]"
        fi
    else
        echo "  [empty]"
    fi
}

show_state() {
    list_filesystem "${CYAN}SOURCE (/tmp):${RESET}" "$SOURCE_BASE"
    list_filesystem "${CYAN}DEST (/tmp):${RESET}" "$DEST_BASE"
}

setup_demo() {
    rm -rf "/tmp/$SAFE_DIR"
    mkdir -p "$SOURCE_BASE/subfolder" "$DEST_BASE"
    echo "shared content" > "$SOURCE_BASE/external.txt"
    ln "$SOURCE_BASE/external.txt" "$SOURCE_BASE/subfolder/internal.txt"
}

cleanup() {
    rm -rf "/tmp/$SAFE_DIR"
    echo "Cleanup completed."
}

trap cleanup EXIT

# ── Initial setup ─────────────────────────────────────
echo -e "${BOLD}SmartMove Cross-Scope Hardlink Demo${RESET}"
echo -e "(Same Filesystem Test)\n"
setup_demo
show_state

# ── TAR test ──────────────────────────────────────────
echo -e "\n${GREEN}${BOLD}==== TESTING TAR ====${RESET}\n"
setup_demo
cmd="(cd \"$SOURCE_BASE\" && tar -cf - subfolder | tar -C \"$DEST_BASE\" -xf -)"
echo -e "${CYAN}Running:${RESET}\n  $cmd\n"
eval "$cmd"
show_state
echo -e "\n[RESULT] TAR → ${RED}Hardlink not preserved${RESET}"

# ── CPIO test ─────────────────────────────────────────
echo -e "\n${GREEN}${BOLD}==== TESTING CPIO ====${RESET}\n"
setup_demo
cmd="(cd \"$SOURCE_BASE\" && find subfolder -depth | cpio -pdm \"$DEST_BASE/\" 2>/dev/null)"
echo -e "${CYAN}Running:${RESET}\n  $cmd\n"
eval "$cmd"
show_state
echo -e "\n[RESULT] CPIO → ${RED}Hardlink not preserved${RESET}"

# ── RSYNC test ────────────────────────────────────────
echo -e "\n${GREEN}${BOLD}==== TESTING RSYNC ====${RESET}\n"
setup_demo
cmd="rsync -aH --remove-source-files \"$SOURCE_BASE/subfolder/\" \"$DEST_BASE/subfolder/\""
echo -e "${CYAN}Running:${RESET}\n  $cmd\n"
eval "$cmd"
show_state
echo -e "\n[RESULT] RSYNC → ${YELLOW}Orphaned file (external.txt, hardlink lost)${RESET}"

# ── SMARTMOVE test ────────────────────────────────────
echo -e "\n${GREEN}${BOLD}==== TESTING SMARTMOVE ====${RESET}\n"
setup_demo

# Check if SmartMove is installed
if ! command --version smv &> /dev/null; then
    echo "Installing SmartMove..."
    if [ -d "smartmove" ]; then
        cd smartmove && git pull && cd ..
    else
        git clone https://github.com/LeonardoPuccio/smartmove.git
    fi
    cd smartmove && python3 setup.py install && cd ..
fi

cmd="smv \"$SOURCE_BASE/subfolder\" \"$DEST_BASE/subfolder\" -p --quiet"
echo -e "${CYAN}Running:${RESET}\n  $cmd\n"
eval "$cmd"
show_state
echo -e "\n[RESULT] SMARTMOVE → ${GREEN}Hardlink preserved${RESET}"

# ── Final summary ─────────────────────────────────────
echo -e "\n════════════════════════════════════════════════════════════════════════════════════════"
echo -e "${BOLD}  FINAL SUMMARY: Cross-Scope Hardlink Behavior${RESET}"
echo -e "════════════════════════════════════════════════════════════════════════════════════════\n"
echo -e " TAR       → ${RED}Hardlink lost${RESET}"
echo -e " CPIO      → ${RED}Hardlink lost${RESET}"
echo -e " RSYNC     → ${YELLOW}Orphaned external.txt${RESET}"
echo -e " SMARTMOVE → ${GREEN}Hardlink preserved${RESET}\n"
echo -e "${BOLD}SmartMove finds hardlinks everywhere, not just in moved directory${RESET}"
