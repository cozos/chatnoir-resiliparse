#!/usr/bin/env bash
#
# Reproduce the comparison with Marin's fork: build the variants, run every extraction over the dumped HTML
# records, run the demos and print the analysis.
#
# Usage: run_all.sh <records.bin> [--from-source]     (records.bin from bench.py dump)
#
# Outputs go to $BENCH_DIR/marin (default: .bench/marin in the repository root).

set -euo pipefail

HERE=$(dirname "$(realpath "$0")")
REPO=$(git -C "$HERE" rev-parse --show-toplevel)
BENCH_DIR=${BENCH_DIR:-$REPO/.bench}
RECORDS=$(realpath "$1")
FROM_SOURCE=${2:-}
OUT="$BENCH_DIR/marin"
VENVS="$BENCH_DIR/venvs"
BUILD="$HERE/../build.sh"
export BENCH_DIR

# Marin's upstream base predates Cython 3.1 support
CYTHON='cython<3.1' "$BUILD" upstream-2024 7a64d4508d7caf97b2973152b7ba8d91a157e3d8 $FROM_SOURCE
"$BUILD" marin origin/marin/main-legacy $FROM_SOURCE
"$BUILD" upstream v1.0.9 $FROM_SOURCE
"$BUILD" ours origin/datology/perf-1.0.9 $FROM_SOURCE

# Marin's production converter and the versions of its dependencies in Marin's uv.lock
"$HERE/marin_shim.sh" "$BENCH_DIR/marin-shim"
uv pip install -q -p "$VENVS/marin/bin/python" markdownify==1.2.2 beautifulsoup4==4.14.3 draccus==0.11.6 \
    regex==2026.1.14

mkdir -p "$OUT"
cd "$OUT"
: > timings.jsonl
extract() { "$VENVS/$1/bin/python" "$HERE/extract.py" "$2" "$RECORDS" "out-$3.jsonl" | tee -a timings.jsonl; }
extract upstream-2024 plain upstream-2024
extract marin plain marin
MARIN_SHIM="$BENCH_DIR/marin-shim" extract marin marin_full marin-markdown
extract upstream plain upstream
extract ours plain ours
extract upstream all_text visible

for v in upstream-2024 marin upstream; do
    echo "== demo: $v"
    "$VENVS/$v/bin/python" "$HERE/demo.py"
done
python3 "$HERE/analyze.py"
