"""Shared FITS compression logic for the DECaLS storage/compression study.

Used by both the local driver (``scripts/run_local.py``) and the S3-triggered
Lambda (``lambda/lambda_function.py``) so the two produce identical output.
"""

from decals_compression.core import (
    CSV_FIELDS,
    build_rows,
    cutout_id,
    load_image,
    local_noise_mad,
    parse_coords,
    reconstruction_error,
    write_compressed,
    write_lossless,
)

__all__ = [
    "CSV_FIELDS",
    "build_rows",
    "cutout_id",
    "load_image",
    "local_noise_mad",
    "parse_coords",
    "reconstruction_error",
    "write_compressed",
    "write_lossless",
]
