#!/usr/bin/env bash
#
# Copy Marin's HTML-to-Markdown code (marin.web.convert and what it imports) into <dir>, so extract.py can run
# Marin's production convert_page() without installing Marin and its dependencies.
#
# Usage: marin_shim.sh <dir> [marin commit]

set -euo pipefail

OUT=$(realpath -m "$1")
REF=${2:-86fc7b67c921ad4ac124835ca7379b04ffa1be25}
SRC="$OUT/.marin"

if [ ! -d "$SRC" ]; then
    git clone -q --filter=blob:none --no-checkout https://github.com/marin-community/marin "$SRC"
fi
git -C "$SRC" checkout -q "$REF"

M="$SRC/lib/marin/src/marin"
mkdir -p "$OUT/marin/schemas/web"
# Empty package markers: Marin's own marin/__init__.py imports far more than the converter needs
touch "$OUT/marin/__init__.py" "$OUT/marin/schemas/__init__.py" "$OUT/marin/schemas/web/__init__.py"
cp -r "$M/markdown" "$OUT/marin/"
cp "$M/schemas/web/convert.py" "$OUT/marin/schemas/web/convert.py"
cp "$M/web/convert.py" "$OUT/marin_web_convert.py"
echo "Marin $REF converter in $OUT"
