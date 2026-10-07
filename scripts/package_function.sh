#!/usr/bin/env bash
# Package the Lambda function code: the handler plus the shared
# decals_compression package, both at the zip root.
#
# Usage:
#   scripts/package_function.sh                # -> build/function.zip
#
# Then deploy it (placeholders, run yourself):
#   aws lambda update-function-code --function-name FUNCTION_NAME \
#     --zip-file fileb://build/function.zip
set -euo pipefail

ROOT="$(cd "$(dirname "$0")/.." && pwd)"
STAGE="$ROOT/build/function"
OUT="$ROOT/build/function.zip"

rm -rf "$STAGE" "$OUT"
mkdir -p "$STAGE"
cp "$ROOT/lambda/lambda_function.py" "$STAGE/"
cp -R "$ROOT/src/decals_compression" "$STAGE/"
find "$STAGE" -name "__pycache__" -type d -prune -exec rm -rf {} +

(cd "$STAGE" && zip -qr9 "$OUT" .)
echo "Built $OUT:"
unzip -l "$OUT"
