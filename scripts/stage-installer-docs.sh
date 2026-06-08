#!/usr/bin/env bash
set -euo pipefail

cd "$(dirname "$0")/.."

if [[ $# -ne 1 ]]; then
  echo "Usage: scripts/stage-installer-docs.sh <installer-payload-dir>" >&2
  exit 64
fi

payload_dir="$1"
docs_target="$payload_dir/docs_html"

scripts/build-docs.sh

mkdir -p "$payload_dir"
rm -rf "$docs_target"
mkdir -p "$docs_target"
cp -a docs_html/. "$docs_target/"

required_paths=(
  "$docs_target/index.html"
  "$docs_target/quick-start.html"
  "$docs_target/workflows"
  "$docs_target/concepts"
  "$docs_target/_static"
)

for required_path in "${required_paths[@]}"; do
  if [[ ! -e "$required_path" ]]; then
    echo "Missing staged documentation payload path: $required_path" >&2
    exit 1
  fi
done

echo "Staged offline docs at $docs_target"
