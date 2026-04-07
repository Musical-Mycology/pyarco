#!/usr/bin/env python3
"""Generate Python ugen wrapper classes from Arco .ugen DSL files."""

import argparse
import sys
from pathlib import Path

# Add project root to path so tools package is importable
sys.path.insert(0, str(Path(__file__).parent.parent))

from tools.ugen_parser import parse_ugen_file
from tools.ugen_codegen import generate_file


def main():
    parser = argparse.ArgumentParser(
        description="Generate Python ugen wrappers from .ugen files")
    parser.add_argument("ugens_dir",
                        help="Path to directory containing .ugen files")
    parser.add_argument("-o", "--output",
                        default="python25/arco_generated.py",
                        help="Output file path (default: python25/arco_generated.py)")
    args = parser.parse_args()

    ugens_dir = Path(args.ugens_dir)
    if not ugens_dir.is_dir():
        print(f"Error: {ugens_dir} is not a directory", file=sys.stderr)
        sys.exit(1)

    ugen_files = sorted(ugens_dir.rglob("*.ugen"))
    if not ugen_files:
        print(f"No .ugen files found in {ugens_dir}", file=sys.stderr)
        sys.exit(1)

    all_signatures = []
    source_names = []
    for ugen_file in ugen_files:
        try:
            sigs = parse_ugen_file(ugen_file)
            all_signatures.extend(sigs)
            source_names.append(ugen_file.name)
        except Exception as e:
            print(f"Warning: skipping {ugen_file.name}: {e}", file=sys.stderr)

    if not all_signatures:
        print("No valid signatures found", file=sys.stderr)
        sys.exit(1)

    output_content = generate_file(all_signatures, source_names)

    output_path = Path(args.output)
    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(output_content)

    print(f"Generated {len(all_signatures)} classes from {len(source_names)} "
          f"files -> {output_path}")


if __name__ == "__main__":
    main()
