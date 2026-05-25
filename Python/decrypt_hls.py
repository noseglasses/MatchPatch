#!/usr/bin/env python3

import argparse
import base64
import json
import os
import sys
import zlib


def require_extension(path, expected_ext, label):
    ext = os.path.splitext(path)[1].lower()

    if ext != expected_ext:
        raise ValueError(
            f"{label} must have extension "
            f"{expected_ext}, got {ext or '<none>'}"
        )


def parse_args():
    parser = argparse.ArgumentParser(
        description="Decrypt/unpack a Helix .hls file to JSON"
    )

    parser.add_argument(
        "-i",
        "--input",
        required=True,
        help="Input .hls file"
    )

    parser.add_argument(
        "-o",
        "--output",
        required=True,
        help="Output .json file"
    )

    return parser.parse_args()


def main():
    args = parse_args()

    require_extension(args.input, ".hls", "Input")
    require_extension(args.output, ".json", "Output")

    with open(args.input, "r", encoding="utf-8") as f:
        wrapper = json.load(f)

    compressed = base64.b64decode(wrapper["encoded_data"])
    raw = zlib.decompress(compressed)
    text = raw.decode("utf-8")

    with open(args.output, "w", encoding="utf-8") as f:
        f.write(text)


if __name__ == "__main__":
    try:
        main()
    except Exception as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        sys.exit(1)
