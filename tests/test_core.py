"""Offline tests for the shared compression module and the Lambda handler."""

from __future__ import annotations

import csv
import io
import os
import shutil
from pathlib import Path
from typing import Dict, List

import numpy as np
import pytest
from astropy.io import fits

from decals_compression import core
from decals_compression.config import parse_levels

# Must match the Athena DDL in sql/ column for column.
EXPECTED_COLUMNS = [
    "cutout_id", "label", "ra", "dec", "layer", "size_pix", "pixscale",
    "setting", "quantize_level", "size_bytes", "pct_of_lossless",
    "noise_mad", "s3_key",
    "rms_error", "max_abs_error", "rms_over_noise",
]
LEVELS = [16, 24, 32, 64, 128, 256, 512]


def _noisy_image(sigma: float = 2.0, n: int = 256, seed: int = 0) -> np.ndarray:
    """Gaussian noise on a smooth gradient plus one bright extended 'galaxy'."""
    rng = np.random.default_rng(seed)
    y, x = np.mgrid[0:n, 0:n]
    smooth = 100 + 0.2 * x + 0.1 * y + 30 * np.exp(-((x - n / 2) ** 2 + (y - n / 2) ** 2) / (2 * 30 ** 2))
    return (smooth + rng.normal(0, sigma, (n, n))).astype(np.float32)


# --- noise estimate ---------------------------------------------------------

@pytest.mark.parametrize("sigma", [1.0, 2.0, 10.0])
def test_local_noise_recovers_gaussian_sigma(sigma: float) -> None:
    # Steep structure (gradient comparable to sigma per pixel) biases the
    # estimate upward; the synthetic galaxy here is gentle enough to stay
    # within a few percent.
    est = core.local_noise_mad(_noisy_image(sigma))
    assert est == pytest.approx(sigma, rel=0.03)


def test_local_noise_ignores_smooth_structure() -> None:
    # A global MAD would be dominated by the gradient and the galaxy;
    # adjacent-pixel differences should not be.
    img = _noisy_image(1.0)
    global_mad = 1.4826 * np.median(np.abs(img - np.median(img)))
    assert global_mad > 5
    assert core.local_noise_mad(img) == pytest.approx(1.0, rel=0.03)


def test_local_noise_handles_nans() -> None:
    img = _noisy_image(2.0)
    img[:, ::7] = np.nan
    assert core.local_noise_mad(img) == pytest.approx(2.0, rel=0.05)
    assert np.isnan(core.local_noise_mad(np.full((8, 8), np.nan, dtype=np.float32)))


# --- reconstruction error ---------------------------------------------------

def test_reconstruction_error_is_zero_for_lossless(tmp_path: Path) -> None:
    # RICE_1 on integer data is lossless (quantization only applies to floats).
    ints = np.random.default_rng(1).integers(0, 5000, (128, 128)).astype(np.int32)
    path = str(tmp_path / "lossless_rice.fits")
    core.write_compressed(ints, fits.Header(), 16, path)
    rms, max_abs = core.reconstruction_error(ints.astype(np.float32), path)
    assert rms == 0.0
    assert max_abs == 0.0


def test_reconstruction_error_halves_when_level_doubles(tmp_path: Path) -> None:
    img = _noisy_image(2.0)
    rms = {}
    for q in (16, 32, 64):
        path = str(tmp_path / f"q{q}.fits")
        core.write_compressed(img, fits.Header(), q, path)
        rms[q], _ = core.reconstruction_error(img, path)
    assert rms[16] / rms[32] == pytest.approx(2.0, rel=0.1)
    assert rms[32] / rms[64] == pytest.approx(2.0, rel=0.1)


# --- compression size -------------------------------------------------------

def test_size_decreases_as_quantize_level_decreases(tmp_path: Path) -> None:
    img = _noisy_image(2.0)
    lossless = core.write_lossless(img, fits.Header(), str(tmp_path / "lossless.fits"))
    sizes = [core.write_compressed(img, fits.Header(), q, str(tmp_path / f"q{q}.fits"))
             for q in LEVELS]
    # Sizes are padded to 2880-byte FITS blocks, so allow ties but no increases.
    for coarse, fine in zip(sizes, sizes[1:]):
        assert coarse <= fine
    assert sizes[0] < sizes[-1] < lossless


# --- manifest schema --------------------------------------------------------

def _rows(tmp_path: Path, uploads: List[str]) -> List[Dict]:
    return core.build_rows(
        _noisy_image(2.0, n=64), fits.Header(),
        cid="ra150.120_dec+2.200", label="test", ra=150.12, dec=2.2,
        layer="ls-dr10", size_pix=64, pixscale=0.262, quantize_levels=LEVELS,
        work_dir=str(tmp_path), key_prefix="compression-test",
        upload=lambda path, key: uploads.append(key),
    )


def test_csv_fields_unchanged() -> None:
    assert core.CSV_FIELDS == EXPECTED_COLUMNS


def test_manifest_rows_match_schema(tmp_path: Path) -> None:
    uploads: List[str] = []
    rows = _rows(tmp_path, uploads)
    assert [r["setting"] for r in rows] == ["lossless"] + [f"lossy{q}" for q in LEVELS]
    for r in rows:
        assert set(r.keys()) == set(EXPECTED_COLUMNS)
    buf = io.StringIO()
    writer = csv.DictWriter(buf, fieldnames=core.CSV_FIELDS)
    writer.writeheader()
    writer.writerows(rows)
    assert buf.getvalue().splitlines()[0] == ",".join(EXPECTED_COLUMNS)
    lossless = rows[0]
    assert lossless["quantize_level"] == ""
    assert lossless["pct_of_lossless"] == "100.00"
    assert (lossless["rms_error"], lossless["max_abs_error"], lossless["rms_over_noise"]) == ("0", "0", "0")
    assert uploads == [f"compression-test/ra150.120_dec+2.200/{s}.fits"
                       for s in ["lossless"] + [f"lossy{q}" for q in LEVELS]]
    assert os.listdir(tmp_path) == []  # local files cleaned up


def test_lambda_handler_writes_manifest_with_header(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    import lambda_function

    src = tmp_path / "ra150.120_dec+2.200_source.fits"
    fits.PrimaryHDU(_noisy_image(2.0, n=64)).writeto(src)

    class FakeS3:
        def __init__(self) -> None:
            self.objects: Dict[str, bytes] = {}
            self.uploads: List[str] = []

        def download_file(self, bucket: str, key: str, dest: str) -> None:
            shutil.copyfile(src, dest)

        def upload_file(self, path: str, bucket: str, key: str) -> None:
            self.uploads.append(key)

        def put_object(self, Bucket: str, Key: str, Body: bytes) -> None:  # noqa: N803
            self.objects[Key] = Body

    fake = FakeS3()
    monkeypatch.setattr(lambda_function, "s3", fake)
    event = {"Records": [
        {"s3": {"bucket": {"name": "b"}, "object": {"key": "source/ra150.120_dec%2B2.200_source.fits"}}},
        {"s3": {"bucket": {"name": "b"}, "object": {"key": "compression-test/x/lossy16.fits"}}},
    ]}
    result = lambda_function.lambda_handler(event, None)

    assert result == {"processed": [("ra150.120_dec+2.200", len(LEVELS) + 1)]}
    body = fake.objects["manifests-lambda/ra150.120_dec+2.200.csv"].decode()
    reader = csv.reader(io.StringIO(body))
    assert next(reader) == EXPECTED_COLUMNS
    first = dict(zip(EXPECTED_COLUMNS, next(reader)))
    assert (first["ra"], first["dec"], first["size_pix"]) == ("150.12", "2.2", "64")
    assert len(fake.uploads) == len(LEVELS) + 1


# --- helpers ----------------------------------------------------------------

def test_cutout_id_round_trip() -> None:
    cid = core.cutout_id(54.621, -35.451)
    assert cid == "ra54.621_dec-35.451"
    assert core.parse_coords(cid) == (54.621, -35.451)
    assert core.parse_coords("not_a_cutout") == ("", "")


def test_parse_levels() -> None:
    assert parse_levels("16, 32,64") == [16, 32, 64]
    with pytest.raises(ValueError):
        parse_levels("16,-4")
