#!/usr/bin/env bash
# Build a Lambda layer zip containing astropy + numpy for the Lambda runtime.
#
# Downloads manylinux wheels for the target Python/architecture, so it works
# from macOS without Docker. boto3 is already in the Lambda runtime.
#
# Usage:
#   scripts/build_layer.sh                     # -> build/astropy-layer.zip
#   PYTHON_VERSION=3.12 ARCH=arm64 scripts/build_layer.sh
#   ASTROPY_SPEC="astropy==8.0.1" NUMPY_SPEC="numpy==2.2.6" scripts/build_layer.sh
#
# Then publish it (placeholders, run yourself):
#   aws lambda publish-layer-version --layer-name astropy-numpy \
#     --zip-file fileb://build/astropy-layer.zip \
#     --compatible-runtimes python3.12 --compatible-architectures x86_64
set -euo pipefail

PYTHON_VERSION="${PYTHON_VERSION:-3.12}"
ARCH="${ARCH:-x86_64}"                  # x86_64 or arm64
ASTROPY_SPEC="${ASTROPY_SPEC:-astropy}"
NUMPY_SPEC="${NUMPY_SPEC:-numpy}"

case "$ARCH" in
  x86_64) PLATFORM="manylinux2014_x86_64" ;;
  arm64)  PLATFORM="manylinux2014_aarch64" ;;
  *) echo "ARCH must be x86_64 or arm64, got '$ARCH'" >&2; exit 1 ;;
esac

ROOT="$(cd "$(dirname "$0")/.." && pwd)"
BUILD="$ROOT/build/layer"
OUT="$ROOT/build/astropy-layer.zip"

rm -rf "$BUILD" "$OUT"
mkdir -p "$BUILD/python"

python3 -m pip install \
  --quiet \
  --target "$BUILD/python" \
  --platform "$PLATFORM" \
  --implementation cp \
  --python-version "$PYTHON_VERSION" \
  --only-binary=:all: \
  "$ASTROPY_SPEC" "$NUMPY_SPEC"

# Trim things the runtime never needs.
find "$BUILD/python" -type d \( -name "__pycache__" \) -prune -exec rm -rf {} +

(cd "$BUILD" && zip -qr9 "$OUT" python)
echo "Built $OUT ($(du -h "$OUT" | cut -f1)) for python$PYTHON_VERSION/$ARCH"
