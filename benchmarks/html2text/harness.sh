#!/usr/bin/env bash
#
# Compare HTML extraction setups for speed, identical output and quality. See RUNBOOK.md for what it proves and how
# to read the results.
#
# Usage: harness.sh [--warcs N] [--limit RECORDS] [--wmb FILE] [--ours REF] [--from-source]
#
#   --warcs N        use the first N files of warcs.tsv (default: all 18)
#   --limit RECORDS  HTML records per WARC (default: 8000)
#   --wmb FILE       WebMainBench's webmainbench.jsonl; adds the quality comparison (skipped without it)
#   --ours REF       git ref of this fork to build as "ours" (default: HEAD)
#   --from-source    passed to build.sh when vcpkg can't download sources
#
# Setups:
#   upstream    upstream Resiliparse v1.0.9, built from source like the others
#   ours        this fork's Cython extractor (must give byte-identical output to upstream)
#   marin-rust  Marin's learned Rust extractor (resiliparse-rs extract.rs), run by rp-bench with its champion model
#
# Needs VCPKG_ROOT (see README.md), cargo, libclang, uv, Python 3.11 and about 25 GB of disk for all WARCs.
# Outputs go to $BENCH_DIR/harness (default: .bench/harness in the repository root).

set -euo pipefail

HERE=$(dirname "$(realpath "$0")")
REPO=$(git -C "$HERE" rev-parse --show-toplevel)
BENCH_DIR=${BENCH_DIR:-$REPO/.bench}
export BENCH_DIR
OUT="$BENCH_DIR/harness"
VENVS="$BENCH_DIR/venvs"

WARCS=""
LIMIT=8000
WMB=""
OURS=HEAD
FROM_SOURCE=""
while [ $# -gt 0 ]; do
    case $1 in
        --warcs) WARCS=$2; shift 2 ;;
        --limit) LIMIT=$2; shift 2 ;;
        --wmb) WMB=$(realpath "$2"); shift 2 ;;
        --ours) OURS=$2; shift 2 ;;
        --from-source) FROM_SOURCE=--from-source; shift ;;
        *) echo "Unknown argument: $1" >&2; exit 2 ;;
    esac
done

# Champion model from Marin's kit, plus the fastText model it takes one feature from (807 MB, BSD-2-Clause)
FOREST="$REPO/benchmark-extract/stack_rf8.json"
FT="$BENCH_DIR/models/general_ft.bin"
THRESHOLD=0.60
FT_URL=https://huggingface.co/MichaelR207/justext-classifier/resolve/main/general_ft.bin

mkdir -p "$OUT" "$BENCH_DIR/warcs" "$BENCH_DIR/models"
cd "$OUT"

echo "== Building setups"
git -C "$REPO" rev-parse -q --verify v1.0.9 > /dev/null || {
    git -C "$REPO" remote get-url upstream > /dev/null 2>&1 ||
        git -C "$REPO" remote add upstream https://github.com/chatnoir-eu/chatnoir-resiliparse
    git -C "$REPO" fetch -q upstream tag v1.0.9
}
"$HERE/build.sh" upstream v1.0.9 $FROM_SOURCE
"$HERE/build.sh" ours "$OURS" $FROM_SOURCE
uv pip install -q -p "$VENVS/upstream/bin/python" jieba==0.42.1
# resiliparse-rs's build script runs vcpkg itself; on Linux arm64 use the tree's triplet, as deps.sh does
[ "$(uname -s)-$(uname -m)" = Linux-aarch64 ] && export VCPKG_DEFAULT_TRIPLET=aarch64-linux
PATH="${VCPKG_ROOT:?Set VCPKG_ROOT}:$PATH" cargo build -q --release \
    --manifest-path "$REPO/benchmark-extract/rp-bench/Cargo.toml"
RP="$REPO/benchmark-extract/rp-bench/target/release/rp-bench"
[ -f "$FT" ] || curl -fL --retry 3 -o "$FT" "$FT_URL"
rp() { RAYON_NUM_THREADS=1 "$RP" "$1" "$2" --mode para --ft "$FT" --stack "$FOREST" --threshold "$THRESHOLD"; }

echo "== Speed and identical output on Common Crawl"
python3 "$HERE/warcs.py" fetch "$HERE/warcs.tsv" "$BENCH_DIR/warcs" ${WARCS:+--limit $WARCS}
PY="$VENVS/upstream/bin/python"
while IFS=$'\t' read -r crawl name; do
    dir="$OUT/warcs/$crawl"
    mkdir -p "$dir"
    [ -f "$dir/records.bin" ] || "$PY" "$HERE/bench.py" dump "$BENCH_DIR/warcs/$name" "$dir/records.bin"
    for v in upstream ours; do
        "$VENVS/$v/bin/python" "$HERE/bench.py" run "$dir/records.bin" "$dir/$v.json" --limit "$LIMIT" --repeat 2
    done
    "$PY" "$HERE/bench.py" export "$dir/records.bin" "$dir/records.jsonl.gz" --limit "$LIMIT"
    rp "$dir/records.jsonl.gz" "$dir/marin-rust.predictions.jsonl"
    "$PY" "$HERE/bench.py" from-rp "$dir/marin-rust.predictions.jsonl" "$dir/marin-rust.json"
    echo "-- $crawl"
    "$PY" "$HERE/bench.py" compare "$dir/upstream.json" "$dir/ours.json" "$dir/marin-rust.json" | tee "$dir/compare.txt"
done < <(python3 "$HERE/warcs.py" list "$HERE/warcs.tsv" ${WARCS:+--limit $WARCS})

for v in upstream ours marin-rust; do
    "$PY" "$HERE/bench.py" merge "$OUT/all-$v.json" "$OUT"/warcs/*/"$v.json" > /dev/null
done
echo "-- all WARCs"
"$PY" "$HERE/bench.py" compare "$OUT/all-upstream.json" "$OUT/all-ours.json" "$OUT/all-marin-rust.json" \
    | tee "$OUT/compare-all.txt"

if [ -z "$WMB" ]; then
    echo "== Quality: skipped (pass --wmb webmainbench.jsonl)"
    exit 0
fi
echo "== Quality on WebMainBench (English pages, human-annotated references)"
[ -f "$OUT/wmb_en.jsonl.gz" ] || "$PY" "$REPO/benchmark-extract/wmb_convert.py" "$WMB" "$OUT/wmb_en.jsonl.gz"
for v in upstream ours; do
    "$VENVS/$v/bin/python" "$HERE/bench.py" predict "$OUT/wmb_en.jsonl.gz" "$OUT/wmb-$v.predictions.jsonl"
done
rp "$OUT/wmb_en.jsonl.gz" "$OUT/wmb-marin-rust.predictions.jsonl"
"$PY" "$HERE/quality.py" "$OUT/wmb_en.jsonl.gz" --json "$OUT/quality-wmb.json" \
    upstream="$OUT/wmb-upstream.predictions.jsonl" ours="$OUT/wmb-ours.predictions.jsonl" \
    marin-rust="$OUT/wmb-marin-rust.predictions.jsonl" | tee "$OUT/quality-wmb.txt"
