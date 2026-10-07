"""Compression, error measurement and manifest-row building.

Recipe: RICE_1 tile compression with SUBTRACTIVE_DITHER_2 quantization, the
same as the Butler ``writeRecipes.yaml`` "lossy16" entry, at several quantize
levels, plus an uncompressed (lossless) baseline.

Output contract (do not change without migrating the Athena tables):
  * the column order of ``CSV_FIELDS``;
  * the string formatting of each value in ``build_rows``;
  * the ``CompImageHDU`` arguments in ``write_compressed``. In particular
    ``dither_seed`` is left at the astropy default (clock-based), as in the
    original runs. File sizes are deterministic; raw bytes are not.
"""

from __future__ import annotations

import logging
import os
import re
from typing import Callable, Dict, List, Optional, Sequence, Tuple, Union

import numpy as np
from astropy.io import fits

logger = logging.getLogger(__name__)

# Column order is load-bearing: the Athena external tables map columns by
# position. Append new columns at the end, never reorder.
CSV_FIELDS: List[str] = [
    "cutout_id", "label", "ra", "dec", "layer", "size_pix", "pixscale",
    "setting", "quantize_level", "size_bytes", "pct_of_lossless",
    "noise_mad", "s3_key",
    "rms_error", "max_abs_error", "rms_over_noise",
]

# 1.4826 converts a MAD to a Gaussian sigma; dividing by sqrt(2) converts the
# sigma of a difference of two independent pixels back to a per-pixel sigma.
_MAD_TO_SIGMA = 1.4826
_COORD_RE = re.compile(r"ra([\d.]+)_dec([+-][\d.]+)")

Row = Dict[str, Union[str, int, float]]
Uploader = Callable[[str, str], None]


def cutout_id(ra: float, dec: float) -> str:
    """Canonical cutout identifier, e.g. ``ra150.120_dec+2.200``."""
    return f"ra{ra:.3f}_dec{dec:+.3f}"


def parse_coords(cid: str) -> Tuple[Union[float, str], Union[float, str]]:
    """Recover (ra, dec) from a cutout id. Returns ``("", "")`` if it doesn't parse."""
    m = _COORD_RE.match(cid)
    if not m:
        return "", ""
    return float(m.group(1)), float(m.group(2))


def load_image(path: str) -> Tuple[np.ndarray, fits.Header]:
    """Read the primary HDU of a FITS file as float32 data plus a header copy."""
    with fits.open(path) as hdul:
        data = np.array(hdul[0].data, dtype=np.float32)
        header = hdul[0].header.copy()
    return data, header


def local_noise_mad(data: np.ndarray) -> float:
    """Local noise estimate, reported in the manifest as ``noise_mad``.

    This is a MAD-based sigma of *adjacent-pixel differences* along the last
    axis, not a global MAD of the pixel values. Differencing neighbours
    cancels smooth structure (sky gradients, extended galaxy light), so the
    result tracks the pixel-to-pixel noise, which is closer to what the FITS
    quantizer uses to pick its step size. It is still not the same estimator
    CFITSIO uses internally (see README, "Caveat").

    Returns NaN if there are no finite differences.
    """
    d = np.diff(data, axis=-1).ravel()
    d = d[np.isfinite(d)]
    if d.size == 0:
        return float("nan")
    return float(_MAD_TO_SIGMA * np.median(np.abs(d - np.median(d))) / np.sqrt(2))


def reconstruction_error(original: np.ndarray, path: str) -> Tuple[float, float]:
    """Decompress ``path`` and compare it to ``original``.

    Returns ``(rms_error, max_abs_error)`` over pixels finite in both arrays,
    or ``(nan, nan)`` if there are none.
    """
    with fits.open(path) as hdul:
        recon = np.array(hdul[1].data, dtype=np.float32)
    diff = (recon - original).astype(np.float64)
    diff = diff[np.isfinite(diff)]
    if diff.size == 0:
        return float("nan"), float("nan")
    return float(np.sqrt(np.mean(diff ** 2))), float(np.max(np.abs(diff)))


def write_lossless(data: np.ndarray, header: fits.Header, path: str) -> int:
    """Write an uncompressed primary HDU and return the file size in bytes."""
    fits.PrimaryHDU(data=data, header=header).writeto(path, overwrite=True)
    return os.path.getsize(path)


def write_compressed(data: np.ndarray, header: fits.Header, level: float, path: str) -> int:
    """Write RICE_1 + SUBTRACTIVE_DITHER_2 at ``level`` and return the file size in bytes."""
    hdu = fits.CompImageHDU(
        data=data,
        header=header,
        compression_type="RICE_1",
        quantize_level=level,
        quantize_method=2,  # SUBTRACTIVE_DITHER_2
    )
    hdu.writeto(path, overwrite=True)
    return os.path.getsize(path)


def build_rows(
    data: np.ndarray,
    header: fits.Header,
    *,
    cid: str,
    label: str,
    ra: Union[float, str],
    dec: Union[float, str],
    layer: str,
    size_pix: int,
    pixscale: float,
    quantize_levels: Sequence[int],
    work_dir: str,
    key_prefix: str,
    upload: Optional[Uploader] = None,
    keep_files: bool = False,
) -> List[Row]:
    """Compress one image at every setting and return its manifest rows.

    For the lossless baseline and each quantize level this writes the file to
    ``work_dir``, measures size (and reconstruction error for lossy levels),
    calls ``upload(local_path, s3_key)`` if given, then deletes the local file
    unless ``keep_files`` is set. S3 keys are
    ``<key_prefix>/<cid>/{lossless,lossy<q>}.fits``.

    Rows are dicts keyed by ``CSV_FIELDS``, with values pre-formatted exactly
    as the manifests expect.
    """
    noise = local_noise_mad(data)
    base: Row = {
        "cutout_id": cid, "label": label, "ra": ra, "dec": dec,
        "layer": layer, "size_pix": size_pix, "pixscale": pixscale,
        "noise_mad": f"{noise:.6g}",
    }

    def _finish(path: str, key: str) -> None:
        if upload is not None:
            upload(path, key)
        if not keep_files:
            os.remove(path)

    rows: List[Row] = []

    path = os.path.join(work_dir, f"{cid}_lossless.fits")
    lossless_size = write_lossless(data, header, path)
    key = f"{key_prefix}/{cid}/lossless.fits"
    _finish(path, key)
    rows.append({
        **base, "setting": "lossless", "quantize_level": "",
        "size_bytes": lossless_size, "pct_of_lossless": "100.00",
        "s3_key": key,
        "rms_error": "0", "max_abs_error": "0", "rms_over_noise": "0",
    })
    logger.info("%s lossless: %s bytes", cid, f"{lossless_size:,}")

    for level in quantize_levels:
        path = os.path.join(work_dir, f"{cid}_lossy{level}.fits")
        size = write_compressed(data, header, level, path)
        rms, max_abs = reconstruction_error(data, path)
        key = f"{key_prefix}/{cid}/lossy{level}.fits"
        _finish(path, key)
        rows.append({
            **base, "setting": f"lossy{level}", "quantize_level": level,
            "size_bytes": size,
            "pct_of_lossless": f"{100 * size / lossless_size:.2f}",
            "s3_key": key,
            "rms_error": f"{rms:.6g}",
            "max_abs_error": f"{max_abs:.6g}",
            "rms_over_noise": f"{rms / noise:.6g}" if noise > 0 else "",
        })
        logger.info(
            "%s lossy%s: %s bytes (%.1f%%), rms err = %.4f x noise",
            cid, level, f"{size:,}", 100 * size / lossless_size,
            rms / noise if noise > 0 else float("nan"),
        )

    return rows
