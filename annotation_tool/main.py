"""
main.py — Command-line entry point for the annotation tool.

Usage:
    python -m annotation_tool -f <folder> -c <config>
    python -m annotation_tool -f <folder> -c <config> -o <output_dir> -a <name>
    python -m annotation_tool -f <folder> -c <config> -o <output_dir> -a <name>
"""

import argparse
import os
import sys

from .config import Config
from .data import get_txt_files
from .gui import run_app


def main() -> None:
    parser = argparse.ArgumentParser(
        prog='annotation_tool',
        description='Span-classification annotation tool (slate-compatible output).',
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
  python -m annotation_tool -f ./HT_Feedback_Examples -c config.txt
  python -m annotation_tool -f ./data -c config.txt -o ./output -a alice
  python -m annotation_tool -f ./data -c config.txt -o ./output -a alice

Keyboard shortcuts (in the tool):
  <label key>   Apply / toggle the label on the current selection
  u             Remove all annotations on the current selection
  ]             Next file (auto-saves)
  [             Previous file (auto-saves)
  Ctrl+S        Save current file
  Ctrl+Z        Undo last annotation
  Ctrl+Q        Quit
  Escape        Clear current selection
        """,
    )
    parser.add_argument(
        '-f', '--folder', required=True,
        help='Folder containing .txt files to annotate',
    )
    parser.add_argument(
        '-c', '--config', required=True,
        help='Path to the label configuration file',
    )
    parser.add_argument(
        '-o', '--output', default=None,
        metavar='DIR',
        help=(
            'Directory for .annotations output files.  '
            'Defaults to the same directory as the input files.'
        ),
    )
    parser.add_argument(
        '-a', '--annotator', default='',
        metavar='NAME',
        help=(
            'Annotator name/ID.  Shown in the header and used as part of the '
            'annotation filename (<file>.<name>.annotations) so multiple '
            'annotators can work on the same files independently.'
        ),
    )
    args = parser.parse_args()

    # --- Validate inputs ---------------------------------------------------

    if not os.path.isdir(args.folder):
        print(f"Error: folder not found: {args.folder!r}", file=sys.stderr)
        sys.exit(1)

    if not os.path.isfile(args.config):
        print(f"Error: config file not found: {args.config!r}", file=sys.stderr)
        sys.exit(1)

    try:
        config = Config.from_file(args.config)
    except (ValueError, OSError) as exc:
        print(f"Error reading config: {exc}", file=sys.stderr)
        sys.exit(1)

    files = get_txt_files(args.folder)
    if not files:
        print(f"Error: no .txt files found in {args.folder!r}", file=sys.stderr)
        sys.exit(1)

    # --- Prepare output directory ------------------------------------------

    output_dir = args.output
    if output_dir:
        os.makedirs(output_dir, exist_ok=True)

    # --- Report to console -------------------------------------------------

    print(f"Files   : {len(files)}")
    print(f"Labels  : {', '.join(f'[{lc.key}] {lc.name}' for lc in config.labels.values())}")
    if output_dir:
        print(f"Output  : {output_dir}")
    if args.annotator:
        print(f"Annotator: {args.annotator}")
    print()

    # --- Launch GUI --------------------------------------------------------

    run_app(config, files, output_dir, args.annotator)
