"""
Progress Reporter

Provides a class to report progress of file operations in the terminal.
"""

import locale
import logging
import os
import sys
import time

logger = logging.getLogger(__name__)


class ProgressReporter:
    def __init__(self, total_files, quiet=False, show_progress=True):
        self.total_files = total_files
        self.processed_files = 0
        self.quiet = quiet
        self.show_progress = show_progress and not quiet and total_files > 0
        self.start_time = time.time()
        self.unicode_support = self._detect_unicode()
        self.samples = []

    def _detect_unicode(self):
        """Detect Unicode terminal support"""
        try:
            encoding_ok = sys.stdout.encoding and "utf" in sys.stdout.encoding.lower()

            locale_ok = (
                "utf" in locale.getpreferredencoding().lower()
                or "utf" in os.environ.get("LANG", "").lower()
                or "utf" in os.environ.get("LC_CTYPE", "").lower()
            )

            term_ok = os.environ.get("TERM", "") != "dumb" and sys.stdout.isatty()

            return encoding_ok and locale_ok and term_ok
        except Exception:
            return False

    def _calculate_stats(self):
        """Calculate rate and ETA"""
        now = time.time()
        elapsed = now - self.start_time

        if elapsed < 1:
            return "", ""

        # Current rate
        rate = self.processed_files / elapsed

        # Rate display
        if rate >= 1000:
            rate_str = f" {rate / 1000:.1f}k/s"
        else:
            rate_str = f" {rate:.0f}/s"

        # ETA calculation
        if rate > 0:
            eta_seconds = (self.total_files - self.processed_files) / rate
            eta_str = f" ETA {int(eta_seconds // 60)}:{int(eta_seconds % 60):02d}"
        else:
            eta_str = ""

        return rate_str, eta_str

    def update(self, current_file=None):
        self.processed_files += 1

        if not self.show_progress:
            return

        if self.processed_files % 10 == 0 or self.processed_files == self.total_files:
            pct = int((self.processed_files / self.total_files) * 100)

            # Progress bar
            bar_width = 20
            filled = int(bar_width * pct / 100)

            if self.unicode_support:
                bar = "█" * filled + "░" * (bar_width - filled)
            else:
                empty = bar_width - filled
                arrow = ">" if filled < bar_width and filled > 0 else ""
                spaces = " " * max(0, empty - len(arrow))
                bar = "=" * filled + arrow + spaces

            rate_str, eta_str = self._calculate_stats()

            print(
                f"\r[{bar}] {pct:3d}% {self.processed_files:,}/{self.total_files:,}{rate_str}{eta_str}",
                end="",
                flush=True,
            )

            if self.processed_files == self.total_files:
                print()
