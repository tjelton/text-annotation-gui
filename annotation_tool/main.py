"""
main.py — Command-line entry point for the annotation tool.

Usage:
    python -m annotation_tool -f <folder> -c <config>
    python -m annotation_tool -f <folder> -c <config> -o <output_dir> -a <name>
    python -m annotation_tool adjudicate -f <folder> -c <config> -p <path1> <path2>
"""

import argparse
import os
import sys

from .config import Config
from .data import find_annotators, get_txt_files, read_text
from .gui import run_app


def _readable_files(paths: list) -> list:
    """Return the paths that can be read as UTF-8, warning about the rest."""
    readable = []
    for path in paths:
        name = os.path.basename(path)
        try:
            read_text(path)
        except UnicodeDecodeError as exc:
            print(f"Warning: skipping {name!r}: not valid UTF-8 "
                  f"(byte 0x{exc.object[exc.start]:02x} at position {exc.start}). "
                  f"Re-save it with UTF-8 encoding to annotate it.",
                  file=sys.stderr)
        except OSError as exc:
            print(f"Warning: skipping {name!r}: {exc.strerror or exc}",
                  file=sys.stderr)
        else:
            readable.append(path)
    return readable


def main() -> None:
    # If the first positional arg is not a known subcommand, default to 'annotate'
    if len(sys.argv) > 1 and sys.argv[1] not in (
        'annotate', 'adjudicate', '-h', '--help',
    ):
        sys.argv.insert(1, 'annotate')

    parser = argparse.ArgumentParser(
        prog='annotation_tool',
        description='Span-classification annotation tool (slate-compatible output).',
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
  python -m annotation_tool -f ./data -c config.txt
  python -m annotation_tool -f ./data -c config.txt -o ./output -a alice
  python -m annotation_tool adjudicate -f ./data -c config.txt -p ./ann1 ./ann2
        """,
    )
    subparsers = parser.add_subparsers(dest='mode')

    # --- annotate (default) ------------------------------------------------

    ann_parser = subparsers.add_parser(
        'annotate', help='Annotate text files (default mode)',
    )
    ann_parser.add_argument(
        '-f', '--folder', required=True,
        help='Folder containing .txt files to annotate',
    )
    ann_parser.add_argument(
        '-c', '--config', required=True,
        help='Path to the label configuration file',
    )
    ann_parser.add_argument(
        '-o', '--output', default=None, metavar='DIR',
        help='Directory for .annotations output files (default: input folder)',
    )
    ann_parser.add_argument(
        '-a', '--annotator', default='', metavar='NAME',
        help='Annotator name/ID (used in output filename)',
    )

    # --- adjudicate --------------------------------------------------------

    adj_parser = subparsers.add_parser(
        'adjudicate', help='Adjudicate annotations from multiple annotators',
    )
    adj_parser.add_argument(
        '-f', '--folder', required=True,
        help='Folder containing the original .txt files',
    )
    adj_parser.add_argument(
        '-c', '--config', required=True,
        help='Path to the label configuration file',
    )
    adj_parser.add_argument(
        '-p', '--paths', nargs='+', required=True, metavar='DIR',
        help='Paths to annotator folders (one folder per annotator)',
    )
    adj_parser.add_argument(
        '-o', '--output', default=None, metavar='DIR',
        help='Directory for .adjudications.annotations output files (default: input folder)',
    )

    args = parser.parse_args()
    if args.mode is None:
        parser.print_help()
        sys.exit(1)

    # --- Validate common inputs --------------------------------------------

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
    files = _readable_files(files)
    if not files:
        print(f"Error: none of the .txt files in {args.folder!r} could be read",
              file=sys.stderr)
        sys.exit(1)

    output_dir = args.output
    if output_dir:
        os.makedirs(output_dir, exist_ok=True)

    # --- Mode-specific logic -----------------------------------------------

    if args.mode == 'annotate':
        print(f"Files   : {len(files)}")
        print(f"Labels  : {', '.join(f'[{lc.key}] {lc.name}' for lc in config.labels.values())}")
        if output_dir:
            print(f"Output  : {output_dir}")
        if args.annotator:
            print(f"Annotator: {args.annotator}")
        print()
        run_app(config, files, output_dir, args.annotator)

    elif args.mode == 'adjudicate':
        # Validate annotator paths
        for p in args.paths:
            if not os.path.isdir(p):
                print(f"Error: annotator path not found: {p!r}", file=sys.stderr)
                sys.exit(1)

        txt_basenames = [os.path.basename(f) for f in files]
        annotator_data = []
        used_names: set = set()
        seen_dirs: set = set()
        unnamed_counter = 1

        for p in args.paths:
            real = os.path.realpath(p)
            if real in seen_dirs:
                print(f"Warning: {p!r} was given more than once; using it once.",
                      file=sys.stderr)
                continue
            seen_dirs.add(real)

            found = find_annotators(p, txt_basenames)
            if not found:
                print(f"Error: no annotation files for the .txt files in "
                      f"{args.folder!r} were found in {p!r}", file=sys.stderr)
                sys.exit(1)

            for raw_name, file_map in found:
                if raw_name:
                    name = raw_name[0].upper() + raw_name[1:]
                else:
                    name = f"Annotator {unnamed_counter}"
                    unnamed_counter += 1
                # Names key the per-annotator data, so they must be unique
                # (e.g. "alice" in two folders, or "alice" and "Alice").
                unique, n = name, 2
                while unique in used_names:
                    unique = f"{name} ({n})"
                    n += 1
                used_names.add(unique)
                annotator_data.append((unique, file_map))

        print(f"Mode    : Adjudication")
        print(f"Files   : {len(files)}")
        print(f"Labels  : {', '.join(f'[{lc.key}] {lc.name}' for lc in config.labels.values())}")
        print(f"Annotators: {', '.join(name for name, _ in annotator_data)}")
        if output_dir:
            print(f"Output  : {output_dir}")
        print()

        run_app(config, files, output_dir, '',
                adjudication_annotators=annotator_data)
