#!/usr/bin/env python3
"""Local driver: download DECaLS cutouts, compress them, upload results to S3.

For each (label, ra, dec) row in the targets CSV:
  1. Download a fixed-size cutout from the Legacy Survey viewer (cached in
     --work-dir, so re-runs don't re-download).
  2. Write a lossless baseline and RICE_1 / SUBTRACTIVE_DITHER_2 versions at
     each quantize level (same recipe as the Butler "lossy16" entry).
  3. Upload every version to s3://<bucket>/<output-prefix>/<cutout_id>/.
  4. Append one row per (cutout, setting) to a local manifest CSV.

At the end the manifest is uploaded to s3://<bucket>/<manifest-key> for
Athena. With --no-upload nothing touches AWS (boto3 isn't even imported).

Examples:
    python scripts/run_local.py --no-upload
    BUCKET_NAME=my-bucket python scripts/run_local.py
    python scripts/run_local.py --bucket my-bucket --levels 16,64,256
"""

from __future__ import annotations

import argparse
import csv
import logging
import os
import sys
import time
from pathlib import Path
from typing import Callable, List, Optional, Sequence, Tuple

import numpy as np
from astropy.io import fits

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "src"))

from decals_compression import config  # noqa: E402
from decals_compression.core import CSV_FIELDS, build_rows, cutout_id, load_image  # noqa: E402

logger = logging.getLogger("run_local")

CUTOUT_URL = "https://www.legacysurvey.org/viewer/cutout.fits"

Target = Tuple[str, float, float]


def read_targets(path: str) -> List[Target]:
    """Read ``label,ra,dec`` rows from a CSV with a header line."""
    targets: List[Target] = []
    with open(path, newline="") as f:
        for lineno, row in enumerate(csv.DictReader(f), start=2):
            try:
                targets.append((row["label"].strip(), float(row["ra"]), float(row["dec"])))
            except (KeyError, TypeError, ValueError) as e:
                raise ValueError(f"{path}:{lineno}: expected label,ra,dec ({e})") from e
    if not targets:
        raise ValueError(f"{path}: no targets found")
    return targets


def download_cutout(
    ra: float, dec: float, dest: str, *, layer: str, pixscale: float, size_pix: int, bands: str,
) -> bool:
    """Download a cutout FITS to ``dest``. Returns True if it is a valid, non-empty image.

    Coordinates outside the survey footprint come back as an all-zero image;
    those, HTTP errors, and unreadable files return False (and ``dest`` is removed).
    """
    import requests  # only needed for downloads

    params = {"ra": ra, "dec": dec, "layer": layer, "pixscale": pixscale,
              "size": size_pix, "bands": bands}
    try:
        resp = requests.get(CUTOUT_URL, params=params, timeout=120)
    except requests.RequestException as e:
        logger.warning("download failed: %s", e)
        return False
    if resp.status_code != 200:
        logger.warning("HTTP %d from cutout service, skipping", resp.status_code)
        return False

    with open(dest, "wb") as f:
        f.write(resp.content)
    try:
        with fits.open(dest) as hdul:
            data = hdul[0].data
            if data is None or not np.isfinite(data).any() or not np.any(data):
                logger.warning("empty cutout (probably outside footprint), skipping")
                os.remove(dest)
                return False
    except OSError as e:
        logger.warning("not a valid FITS file (%s), skipping", e)
        os.remove(dest)
        return False
    return True


def make_uploader(bucket: str) -> Callable[[str, str], None]:
    """Return ``upload(local_path, key)`` bound to an S3 client and bucket."""
    import boto3  # only needed when uploading

    s3 = boto3.client("s3")

    def upload(path: str, key: str) -> None:
        s3.upload_file(path, bucket, key)

    return upload


def process_target(
    label: str, ra: float, dec: float, writer: csv.DictWriter, args: argparse.Namespace,
    upload: Optional[Callable[[str, str], None]],
) -> bool:
    """Download (if not cached), compress and log one target. Returns False if skipped."""
    cid = cutout_id(ra, dec)
    logger.info("[%s] %s", cid, label)
    src = os.path.join(args.work_dir, f"{cid}_source.fits")

    if not os.path.exists(src):
        if not download_cutout(ra, dec, src, layer=args.layer, pixscale=args.pixscale,
                               size_pix=args.size_pix, bands=args.bands):
            return False
        time.sleep(args.sleep)  # be polite to the Legacy Survey server

    data, header = load_image(src)
    rows = build_rows(
        data, header,
        cid=cid, label=label, ra=ra, dec=dec,
        layer=args.layer, size_pix=args.size_pix, pixscale=args.pixscale,
        quantize_levels=args.levels,
        work_dir=args.work_dir, key_prefix=args.output_prefix,
        upload=upload, keep_files=args.keep_files,
    )
    writer.writerows(rows)
    return True


def parse_args(argv: Optional[Sequence[str]] = None) -> argparse.Namespace:
    env = os.environ
    p = argparse.ArgumentParser(description=__doc__.split("\n\n")[0],
                                formatter_class=argparse.ArgumentDefaultsHelpFormatter)
    p.add_argument("--bucket", default=env.get(config.ENV_BUCKET),
                   help=f"S3 bucket (env {config.ENV_BUCKET}); required unless --no-upload")
    p.add_argument("--output-prefix",
                   default=config.env_str(config.ENV_OUTPUT_PREFIX, config.DEFAULT_OUTPUT_PREFIX),
                   help=f"S3 prefix for compressed files (env {config.ENV_OUTPUT_PREFIX})")
    p.add_argument("--manifest-key",
                   default=config.env_str(config.ENV_MANIFEST_KEY, config.DEFAULT_MANIFEST_KEY),
                   help=f"S3 key for the manifest CSV (env {config.ENV_MANIFEST_KEY})")
    p.add_argument("--levels", type=config.parse_levels,
                   default=config.env_levels(),
                   help=f"comma-separated quantize levels (env {config.ENV_QUANTIZE_LEVELS})")
    p.add_argument("--layer", default=config.env_str(config.ENV_LAYER, config.DEFAULT_LAYER),
                   help=f"Legacy Survey layer (env {config.ENV_LAYER})")
    p.add_argument("--pixscale", type=float, default=config.env_pixscale(),
                   help=f"arcsec/pixel (env {config.ENV_PIXSCALE})")
    p.add_argument("--size-pix", type=int, default=config.DEFAULT_SIZE_PIX,
                   help="cutout width/height in pixels")
    p.add_argument("--bands", default=config.DEFAULT_BANDS)
    p.add_argument("--targets", default="targets.csv", help="CSV with label,ra,dec columns")
    p.add_argument("--work-dir", default="work", help="cache for downloaded cutouts")
    p.add_argument("--csv", default="compression_results_multi.csv", help="local manifest path")
    p.add_argument("--sleep", type=float, default=3.0, help="seconds between downloads")
    p.add_argument("--no-upload", action="store_true", help="skip all S3 uploads")
    p.add_argument("--keep-files", action="store_true",
                   help="keep compressed files in --work-dir instead of deleting them")
    p.add_argument("-v", "--verbose", action="store_true")
    args = p.parse_args(argv)
    if not args.no_upload and not args.bucket:
        p.error(f"--bucket (or ${config.ENV_BUCKET}) is required unless --no-upload is given")
    return args


def main(argv: Optional[Sequence[str]] = None) -> int:
    args = parse_args(argv)
    logging.basicConfig(level=logging.DEBUG if args.verbose else logging.INFO,
                        format="%(asctime)s %(levelname)s %(message)s")

    try:
        targets = read_targets(args.targets)
    except (OSError, ValueError) as e:
        logger.error("could not read targets: %s", e)
        return 2
    os.makedirs(args.work_dir, exist_ok=True)
    upload = None if args.no_upload else make_uploader(args.bucket)

    ok, failed = 0, []
    with open(args.csv, "w", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=CSV_FIELDS)
        writer.writeheader()
        for label, ra, dec in targets:
            try:
                if process_target(label, ra, dec, writer, args, upload):
                    ok += 1
                else:
                    failed.append(label)
            except Exception:
                logger.exception("[%s] failed", label)
                failed.append(label)
            f.flush()

    logger.info("done: %d cutouts succeeded, %d skipped/failed %s", ok, len(failed), failed)
    logger.info("local manifest: %s", args.csv)
    if upload is not None:
        try:
            upload(args.csv, args.manifest_key)
            logger.info("manifest: s3://%s/%s", args.bucket, args.manifest_key)
        except Exception:
            logger.exception("manifest upload failed")
            return 1
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main())
