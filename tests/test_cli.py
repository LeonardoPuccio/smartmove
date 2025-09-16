#!/usr/bin/env python3
"""
CLI tests for smartmove.py to increase coverage
"""

import logging
import os
import shutil
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from smartmove import cli
from smartmove.core import CrossFilesystemMover
from smartmove.utils import DirectoryManager


class TestSmartMoveCLI(unittest.TestCase):
    """Test CLI argument parsing and main function"""

    def setUp(self):
        self.temp_dir = Path(tempfile.mkdtemp())
        self.source_file = self.temp_dir / "source.txt"
        self.dest_file = self.temp_dir / "dest.txt"
        self.source_file.write_text("test content")

    def tearDown(self):
        shutil.rmtree(self.temp_dir, ignore_errors=True)

    def test_main_function_dry_run(self):
        """Test main function with dry-run flag"""

        test_args = [
            "smartmove.py",
            str(self.source_file),
            str(self.dest_file),
            "--dry-run",
        ]

        with patch.object(sys, "argv", test_args):
            with patch("os.geteuid", return_value=0):  # Mock root
                with patch("smartmove.cli.FileMover") as mock_mover:
                    mock_instance = mock_mover.return_value
                    mock_instance.move.return_value = True

                    try:
                        cli.main()
                    except SystemExit as e:
                        if e.code != 0:
                            raise

                    mock_mover.assert_called_once()

    def test_main_function_verbose(self):
        """Test main function with verbose flag"""

        test_args = [
            "smartmove.py",
            str(self.source_file),
            str(self.dest_file),
            "--verbose",
        ]

        with patch.object(sys, "argv", test_args):
            with patch("os.geteuid", return_value=0):  # Mock root
                with patch("smartmove.cli.FileMover") as mock_mover:
                    mock_instance = mock_mover.return_value
                    mock_instance.move.return_value = True

                    try:
                        cli.main()
                    except SystemExit as e:
                        if e.code != 0:
                            raise

                    mock_mover.assert_called_once()

    def test_main_function_verbose_short_flag(self):
        """Test main function with -v flag (short form for verbose)"""

        test_args = [
            "smartmove.py",
            str(self.source_file),
            str(self.dest_file),
            "-v",
        ]

        with patch.object(sys, "argv", test_args):
            with patch("os.geteuid", return_value=0):  # Mock root
                with patch("smartmove.cli.FileMover") as mock_mover:
                    mock_instance = mock_mover.return_value
                    mock_instance.move.return_value = True

                    try:
                        cli.main()
                    except SystemExit as e:
                        if e.code != 0:
                            raise

                    mock_mover.assert_called_once()

    def test_main_function_debug_short_verbose(self):
        """Test main function with debug flag and -v for verbose"""

        test_args = [
            "smartmove.py",
            str(self.source_file),
            str(self.dest_file),
            "-v",
            "--debug",
        ]

        with patch.object(sys, "argv", test_args):
            with patch("os.geteuid", return_value=0):
                with patch("smartmove.cli.FileMover") as mock_mover:
                    mock_instance = mock_mover.return_value
                    mock_instance.move.return_value = True

                    try:
                        cli.main()
                    except SystemExit as e:
                        if e.code != 0:
                            raise

                    mock_mover.assert_called_once()

    def test_main_function_debug_requires_verbose(self):
        """Test that debug flag requires verbose flag"""

        test_args = [
            "smartmove.py",
            str(self.source_file),
            str(self.dest_file),
            "--debug",
        ]

        with patch.object(sys, "argv", test_args):
            with patch("os.geteuid", return_value=0):
                with self.assertRaises(SystemExit):
                    cli.main()

    def test_main_function_comprehensive(self):
        """Test main function with comprehensive flag"""

        test_args = [
            "smartmove.py",
            str(self.source_file),
            str(self.dest_file),
            "--comprehensive",
        ]

        with patch.object(sys, "argv", test_args):
            with patch("os.geteuid", return_value=0):
                with patch("smartmove.cli.FileMover") as mock_mover:
                    mock_instance = mock_mover.return_value
                    mock_instance.move.return_value = True

                    try:
                        cli.main()
                    except SystemExit as e:
                        if e.code != 0:
                            raise

                    # Verify comprehensive flag was passed
                    call_args = mock_mover.call_args
                    self.assertTrue(call_args[0][5])  # comprehensive_scan parameter

    def test_main_function_parents(self):
        """Test main function with parents flag"""

        test_args = [
            "smartmove.py",
            str(self.source_file),
            str(self.dest_file),
            "--parents",
        ]

        with patch.object(sys, "argv", test_args):
            with patch("os.geteuid", return_value=0):
                with patch("smartmove.cli.FileMover") as mock_mover:
                    mock_instance = mock_mover.return_value
                    mock_instance.move.return_value = True

                    try:
                        cli.main()
                    except SystemExit as e:
                        if e.code != 0:
                            raise

                    # Verify parents flag was passed
                    call_args = mock_mover.call_args
                    self.assertTrue(call_args[0][2])  # create_parents parameter

    def test_main_function_quiet(self):
        """Test main function with quiet flag"""

        test_args = [
            "smartmove.py",
            str(self.source_file),
            str(self.dest_file),
            "--quiet",
        ]

        with patch.object(sys, "argv", test_args):
            with patch("os.geteuid", return_value=0):
                with patch("smartmove.cli.FileMover") as mock_mover:
                    mock_instance = mock_mover.return_value
                    mock_instance.move.return_value = True

                    try:
                        cli.main()
                    except SystemExit as e:
                        if e.code != 0:
                            raise

                    # Verify quiet flag was passed
                    call_args = mock_mover.call_args
                    self.assertTrue(call_args[0][4])  # quiet parameter

    def test_main_function_non_root_user(self):
        """Test main function exits for non-root users"""

        test_args = ["smartmove.py", str(self.source_file), str(self.dest_file)]

        with patch.object(sys, "argv", test_args):
            with patch("os.geteuid", return_value=1000):  # Non-root
                with self.assertRaises(SystemExit) as context:
                    cli.main()

                self.assertEqual(context.exception.code, 1)

    def test_main_function_move_failure(self):
        """Test main function handles move failure"""

        test_args = ["smartmove.py", str(self.source_file), str(self.dest_file)]

        with patch.object(sys, "argv", test_args):
            with patch("os.geteuid", return_value=0):
                with patch("smartmove.cli.FileMover") as mock_mover:
                    mock_instance = mock_mover.return_value
                    mock_instance.move.return_value = False  # Simulate failure

                    with self.assertRaises(SystemExit) as context:
                        cli.main()

                    self.assertEqual(context.exception.code, 1)

    def test_main_function_exception_handling(self):
        """Test main function handles exceptions"""

        test_args = ["smartmove.py", str(self.source_file), str(self.dest_file)]

        with patch.object(sys, "argv", test_args):
            with patch("os.geteuid", return_value=0):
                with patch(
                    "smartmove.cli.FileMover", side_effect=ValueError("Test error")
                ):
                    with self.assertRaises(SystemExit) as context:
                        cli.main()

                    self.assertEqual(context.exception.code, 1)

    def test_logging_level_verbose(self):
        """Test logging level setting with verbose flag"""

        test_args = [
            "smartmove.py",
            str(self.source_file),
            str(self.dest_file),
            "--verbose",
        ]

        with patch.object(sys, "argv", test_args):
            with patch("os.geteuid", return_value=0):
                with patch("smartmove.FileMover") as mock_mover:
                    mock_instance = mock_mover.return_value
                    mock_instance.move.return_value = True

                    try:
                        cli.main()
                    except SystemExit as e:
                        if e.code != 0:
                            raise

                    # Check if logging level was set to INFO
                    self.assertEqual(logging.getLogger().level, logging.INFO)

    def test_logging_level_verbose_short_flag(self):
        """Test logging level setting with -v flag"""

        test_args = [
            "smartmove.py",
            str(self.source_file),
            str(self.dest_file),
            "-v",
        ]

        with patch.object(sys, "argv", test_args):
            with patch("os.geteuid", return_value=0):
                with patch("smartmove.FileMover") as mock_mover:
                    mock_instance = mock_mover.return_value
                    mock_instance.move.return_value = True

                    try:
                        cli.main()
                    except SystemExit as e:
                        if e.code != 0:
                            raise

                    # Check if logging level was set to INFO
                    self.assertEqual(logging.getLogger().level, logging.INFO)

    def test_logging_level_debug_short_verbose(self):
        """Test logging level setting with -v and --debug flags"""

        test_args = [
            "smartmove.py",
            str(self.source_file),
            str(self.dest_file),
            "-v",
            "--debug",
        ]

        with patch.object(sys, "argv", test_args):
            with patch("os.geteuid", return_value=0):
                with patch("smartmove.FileMover") as mock_mover:
                    mock_instance = mock_mover.return_value
                    mock_instance.move.return_value = True

                    try:
                        cli.main()
                    except SystemExit as e:
                        if e.code != 0:
                            raise

                    # Check if logging level was set to DEBUG
                    self.assertEqual(logging.getLogger().level, logging.DEBUG)

    def test_logging_level_debug(self):
        """Test logging level setting with debug flag"""

        test_args = [
            "smartmove.py",
            str(self.source_file),
            str(self.dest_file),
            "--verbose",
            "--debug",
        ]

        with patch.object(sys, "argv", test_args):
            with patch("os.geteuid", return_value=0):
                with patch("smartmove.FileMover") as mock_mover:
                    mock_instance = mock_mover.return_value
                    mock_instance.move.return_value = True

                    try:
                        cli.main()
                    except SystemExit as e:
                        if e.code != 0:
                            raise

                    # Check if logging level was set to DEBUG
                    self.assertEqual(logging.getLogger().level, logging.DEBUG)

    def test_logging_level_default(self):
        """Test default logging level"""

        test_args = ["smartmove.py", str(self.source_file), str(self.dest_file)]

        with patch.object(sys, "argv", test_args):
            with patch("os.geteuid", return_value=0):
                with patch("smartmove.FileMover") as mock_mover:
                    mock_instance = mock_mover.return_value
                    mock_instance.move.return_value = True

                    try:
                        cli.main()
                    except SystemExit as e:
                        if e.code != 0:
                            raise

                    # Check if logging level was set to ERROR (default)
                    self.assertEqual(logging.getLogger().level, logging.ERROR)

    def test_cross_filesystem_permission_validation(self):
        """Test permission validation in CrossFilesystemMover"""

        # Test unreadable source
        with patch("os.access") as mock_access:
            mock_access.side_effect = lambda path, mode: (
                mode != os.R_OK if "source" in str(path) else True
            )

            with self.assertRaises(PermissionError) as context:
                CrossFilesystemMover(
                    self.source_file,
                    self.dest_file,
                    dry_run=False,
                    quiet=True,
                    dir_manager=DirectoryManager(dry_run=False),
                )

            self.assertIn("Cannot read source", str(context.exception))

    def test_cross_filesystem_dest_permission_validation(self):
        """Test destination permission validation"""

        # Test unwritable destination
        with patch("os.access") as mock_access:
            # Return False for write access on destination parent
            def access_side_effect(path, mode):
                if str(path) == str(self.dest_file.parent) and mode == os.W_OK:
                    return False
                return True

            mock_access.side_effect = access_side_effect

            with self.assertRaises(PermissionError) as context:
                CrossFilesystemMover(
                    self.source_file,
                    self.dest_file,
                    dry_run=False,
                    quiet=True,
                    dir_manager=DirectoryManager(dry_run=False),
                )

            self.assertIn("Cannot write to destination", str(context.exception))

    def test_cross_filesystem_space_validation_error(self):
        """Test space validation error handling"""

        # Mock shutil.disk_usage to fail
        with patch("shutil.disk_usage", side_effect=OSError("Access denied")):
            with self.assertRaises(RuntimeError) as context:
                CrossFilesystemMover(
                    self.source_file,
                    self.dest_file,
                    dry_run=False,
                    quiet=True,
                    dir_manager=DirectoryManager(dry_run=False),
                )

            self.assertIn("Cannot check destination space", str(context.exception))

    def test_main_function_permission_error_message(self):
        """Test improved permission error message"""

        test_args = ["smartmove.py", str(self.source_file), str(self.dest_file)]

        with patch.object(sys, "argv", test_args):
            with patch("os.geteuid", return_value=1000):  # Non-root
                with patch(
                    "smartmove.FileMover",
                    side_effect=PermissionError("Permission denied"),
                ):
                    with self.assertRaises(SystemExit) as context:
                        cli.main()

                    self.assertEqual(context.exception.code, 1)

    def test_version_flag(self):
        """Test --version flag"""

        test_args = ["smartmove.py", "--version"]

        with patch.object(sys, "argv", test_args):
            with self.assertRaises(SystemExit) as context:
                cli.main()

            # argparse exits with code 0 for --version
            self.assertEqual(context.exception.code, 0)


if __name__ == "__main__":
    unittest.main(verbosity=2)
