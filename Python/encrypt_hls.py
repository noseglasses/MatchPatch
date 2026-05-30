#!/usr/bin/env python3

import argparse
import base64
import binascii
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


def get_extension(path):
    return os.path.splitext(path)[1].lower()


def parse_args():
    parser = argparse.ArgumentParser(
        description=(
            "Encrypt/pack a JSON file to Helix .hls, "
            "or validate/copy a .hlx preset to .hlx"
        )
    )

    parser.add_argument(
        "-i",
        "--input",
        required=True,
        help="Input .json or .hlx file"
    )

    parser.add_argument(
        "-o",
        "--output",
        required=True,
        help="Output .hls file for .json input, or .hlx for .hlx input"
    )

    return parser.parse_args()


def main():
    args = parse_args()

    input_ext = get_extension(args.input)

    if input_ext == ".hlx":
        require_extension(args.output, ".hlx", "Output")

        with open(args.input, "r", encoding="utf-8") as f:
            preset = json.load(f)

        with open(args.output, "w", encoding="utf-8") as f:
            json.dump(preset, f, indent=1)

        return

    require_extension(args.input, ".json", "Input")
    require_extension(args.output, ".hls", "Output")

    with open(args.input, "r", encoding="utf-8") as f:
        text = f.read()

    raw = text.encode("utf-8")
    compressed = zlib.compress(raw)

    wrapper = {
        "compression": {
            "crc32": binascii.crc32(raw) & 0xffffffff,
            "decompressed_size": len(raw),
            "type": "zlib"
        },
        "encoded_data": base64.b64encode(
            compressed
        ).decode("ascii")
    }

    with open(args.output, "w", encoding="utf-8") as f:
        json.dump(wrapper, f)


if __name__ == "__main__":
    try:
        main()
    except Exception as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        sys.exit(1)
