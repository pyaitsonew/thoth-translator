#!/usr/bin/env python3
"""
THOTH - Translator for Hybrid Offline Text Handling

A production-ready offline translation tool for translating CSV/Excel
columns from non-English languages to English, running 100% locally
with no internet required after initial setup.

Usage:
    # GUI mode (default)
    python thoth.py --gui

    # CLI mode
    python thoth.py input.csv -o output.csv

    # Specify columns and language
    python thoth.py input.csv --columns "description,notes" --force-lang rus_Cyrl

    # Use Argos engine instead of NLLB
    python thoth.py input.csv --engine argos

    # Download models
    python -m translator.setup --download-models

    # Run tests
    python thoth.py --test

Author: THOTH Development Team
License: MIT
Version: 1.0.0
"""

import argparse
import sys
from pathlib import Path

# Add translator package to path if running directly
if __name__ == "__main__":
    sys.path.insert(0, str(Path(__file__).parent))


def check_dependencies() -> bool:
    """
    Check if required dependencies are installed.

    Returns:
        True if all dependencies are available
    """
    missing = []

    try:
        import pandas
    except ImportError:
        missing.append("pandas")

    try:
        import yaml
    except ImportError:
        missing.append("pyyaml")

    try:
        import transformers
    except ImportError:
        missing.append("transformers")

    try:
        import torch
    except ImportError:
        missing.append("torch")

    try:
        import fasttext
    except ImportError:
        missing.append("fasttext")

    if missing:
        print("Missing required dependencies:")
        for dep in missing:
            print(f"  - {dep}")
        print("\nInstall with: pip install -r requirements.txt")
        return False

    return True


def main() -> int:
    """
    Main entry point for THOTH.

    Parses command-line arguments and launches either GUI or CLI mode.

    Returns:
        Exit code (0 for success)
    """
    parser = argparse.ArgumentParser(
        prog="thoth",
        description="THOTH - Translator for Hybrid Offline Text Handling",
        epilog="""
Examples:
  thoth --gui                          Launch GUI mode
  thoth input.csv                      Translate input.csv (CLI mode)
  thoth input.csv -o output.csv        Specify output file
  thoth input.csv --engine argos       Use Argos engine
  thoth input.csv --force-lang rus_Cyrl Force Russian as source language
  thoth --test                         Run tests

For more information, see README.md
        """,
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )

    # Mode selection
    parser.add_argument(
        "--gui",
        action="store_true",
        help="Launch graphical user interface",
    )

    # Input file (positional, optional)
    parser.add_argument(
        "input_file",
        nargs="?",
        help="Input CSV or Excel file to translate",
    )

    # Output options
    parser.add_argument(
        "-o", "--output",
        dest="output_file",
        help="Output file path (default: input_translated.csv)",
    )

    # Column selection
    parser.add_argument(
        "-c", "--columns",
        help="Comma-separated list of columns to translate",
    )

    # Language options
    parser.add_argument(
        "-l", "--force-lang",
        dest="force_lang",
        help="Force source language for all columns (e.g., rus_Cyrl)",
    )

    parser.add_argument(
        "-t", "--target-lang",
        dest="target_lang",
        default="eng_Latn",
        help="Target language for translation (default: eng_Latn for English)",
    )
    
    # Engine selection
    parser.add_argument(
        "-e", "--engine",
        choices=["nllb", "argos"],
        help="Translation engine (default: nllb)",
    )

    # Configuration
    parser.add_argument(
        "--config",
        help="Path to configuration file",
    )

    # Output modes
    parser.add_argument(
        "-q", "--quiet",
        action="store_true",
        help="Minimal output",
    )

    parser.add_argument(
        "-v", "--verbose",
        action="store_true",
        help="Verbose output (debug logging)",
    )

    # Batch processing
    parser.add_argument(
        "--batch",
        action="store_true",
        help="Process all CSV/Excel files in current directory",
    )

    parser.add_argument(
        "--batch-dir",
        dest="batch_dir",
        help="Process all CSV/Excel files in specified directory",
    )

    parser.add_argument(
        "--batch-recursive",
        action="store_true",
        dest="batch_recursive",
        help="Process all CSV/Excel files in current directory and all subdirectories",
    )

    # Analysis only
    parser.add_argument(
        "--analyze",
        action="store_true",
        help="Only analyze columns, don't translate",
    )

    # Other commands
    parser.add_argument(
        "--test",
        action="store_true",
        help="Run tests with sample data",
    )

    parser.add_argument(
        "--list-languages",
        action="store_true",
        dest="list_languages",
        help="List all supported languages",
    )

    parser.add_argument(
        "--version",
        action="version",
        version="THOTH 1.2.0",
    )

    args = parser.parse_args()

    # Check dependencies
    if not check_dependencies():
        return 1

    # Handle --list-languages
    if args.list_languages:
        from translator.languages import LanguageMapper
        mapper = LanguageMapper()

        print("\nSupported Languages:")
        print("=" * 70)
        print(f"{'Language':<25} {'NLLB Code':<15} {'Argos':<8} {'Family'}")
        print("-" * 70)

        for lang in sorted(mapper.LANGUAGES, key=lambda x: x.name):
            argos = lang.argos_code if lang.argos_supported else "-"
            print(f"{lang.name:<25} {lang.nllb_code:<15} {argos:<8} {lang.family}")

        print("-" * 70)
        print(f"Total: {len(mapper.LANGUAGES)} languages")
        return 0

    # Handle --test
    if args.test:
        from translator.cli import CLI
        cli = CLI()
        return cli._run_tests()

    # Batch processing mode
    if args.batch or args.batch_dir or args.batch_recursive:
        from translator.cli import CLI
        from pathlib import Path
        import glob

        # Determine search directory
        if args.batch_dir:
            search_dir = Path(args.batch_dir)
            if not search_dir.exists():
                print(f"Error: Directory not found: {args.batch_dir}")
                return 1
        else:
            search_dir = Path.cwd()

        # Find files
        if args.batch_recursive:
            csv_files = list(search_dir.rglob("*.csv")) + list(search_dir.rglob("*.xlsx")) + list(search_dir.rglob("*.xls"))
        else:
            csv_files = list(search_dir.glob("*.csv")) + list(search_dir.glob("*.xlsx")) + list(search_dir.glob("*.xls"))

        # Filter out already-translated files
        csv_files = [f for f in csv_files if "_translated" not in f.stem]

        if not csv_files:
            print(f"No CSV/Excel files found in {search_dir}")
            return 0

        print(f"\n{'='*60}")
        print(f"  THOTH Batch Processing")
        print(f"{'='*60}")
        print(f"  Found {len(csv_files)} file(s) to process")
        print(f"{'='*60}\n")

        # Process each file
        cli = CLI()
        success_count = 0
        fail_count = 0

        for i, file_path in enumerate(csv_files, 1):
            print(f"\n[{i}/{len(csv_files)}] Processing: {file_path.name}")
            print("-" * 40)

            # Build argument list
            cli_args = [str(file_path)]

            if args.columns:
                cli_args.extend(["--columns", args.columns])
            if args.force_lang:
                cli_args.extend(["--force-lang", args.force_lang])
            if args.target_lang:
                cli_args.extend(["--target-lang", args.target_lang])
            if args.engine:
                cli_args.extend(["--engine", args.engine])
            if args.config:
                cli_args.extend(["--config", args.config])
            if args.quiet:
                cli_args.append("--quiet")

            try:
                result = cli.run(cli_args)
                if result == 0:
                    success_count += 1
                else:
                    fail_count += 1
            except Exception as e:
                print(f"  Error: {e}")
                fail_count += 1

        # Summary
        print(f"\n{'='*60}")
        print(f"  Batch Processing Complete")
        print(f"{'='*60}")
        print(f"  Successful: {success_count}")
        print(f"  Failed: {fail_count}")
        print(f"  Total: {len(csv_files)}")
        print(f"{'='*60}\n")

        return 0 if fail_count == 0 else 1

    # Handle --gui or no arguments
    if args.gui or (not args.input_file and not args.test):
        try:
            from translator.gui import run_gui
            from translator.config import Config

            config = Config.load(args.config)
            run_gui(config)
            return 0

        except ImportError as e:
            print(f"GUI dependencies not available: {e}")
            print("Try running in CLI mode: python thoth.py input.csv")
            return 1

        except Exception as e:
            print(f"Error launching GUI: {e}")
            return 1

    # CLI mode
    if args.input_file:
        from translator.cli import CLI

        cli = CLI()
        # Build argument list for CLI
        cli_args = [args.input_file]

        if args.output_file:
            cli_args.extend(["-o", args.output_file])
        if args.columns:
            cli_args.extend(["--columns", args.columns])
        if args.force_lang:
            cli_args.extend(["--force-lang", args.force_lang])
        if args.target_lang:
            cli_args.extend(["--target-lang", args.target_lang])
        if args.engine:
            cli_args.extend(["--engine", args.engine])
        if args.config:
            cli_args.extend(["--config", args.config])
        if args.quiet:
            cli_args.append("--quiet")
        if args.verbose:
            cli_args.append("--verbose")
        if args.analyze:
            cli_args.append("--analyze")

        return cli.run(cli_args)

    # No action specified
    parser.print_help()
    return 0


if __name__ == "__main__":
    sys.exit(main())
