"""Configuration defaults and environment-variable parsing.

Every setting can be overridden with an environment variable (and, for the
local script, a CLI flag). Nothing account-specific lives here: the bucket
has no default and must be supplied.
"""

from __future__ import annotations

import os
from typing import List, Mapping, Optional

DEFAULT_QUANTIZE_LEVELS: List[int] = [16, 24, 32, 64, 128, 256, 512]
DEFAULT_LAYER = "ls-dr10"
DEFAULT_PIXSCALE = 0.262          # arcsec/pixel, DECaLS native
DEFAULT_SIZE_PIX = 512
DEFAULT_BANDS = "grz"
DEFAULT_OUTPUT_PREFIX = "compression-test"
DEFAULT_SOURCE_PREFIX = "source/"
DEFAULT_MANIFEST_KEY = "manifests/compression_manifest.csv"   # local run, one file
DEFAULT_MANIFEST_PREFIX = "manifests-lambda"                  # Lambda, one file per cutout

# Environment variable names.
ENV_BUCKET = "BUCKET_NAME"
ENV_OUTPUT_PREFIX = "OUTPUT_PREFIX"
ENV_SOURCE_PREFIX = "SOURCE_PREFIX"
ENV_MANIFEST_KEY = "MANIFEST_KEY"
ENV_MANIFEST_PREFIX = "MANIFEST_PREFIX"
ENV_QUANTIZE_LEVELS = "QUANTIZE_LEVELS"   # comma-separated, e.g. "16,32,64"
ENV_LAYER = "LS_LAYER"
ENV_PIXSCALE = "LS_PIXSCALE"


def parse_levels(value: str) -> List[int]:
    """Parse ``"16, 24,32"`` into ``[16, 24, 32]``. Raises ValueError on bad input."""
    levels = [int(v) for v in value.replace(" ", "").split(",") if v]
    if not levels or any(q <= 0 for q in levels):
        raise ValueError(f"quantize levels must be positive integers, got {value!r}")
    return levels


def env_str(name: str, default: Optional[str], env: Optional[Mapping[str, str]] = None) -> Optional[str]:
    """Return ``env[name]`` if set and non-empty, else ``default``."""
    env = os.environ if env is None else env
    value = env.get(name, "").strip()
    return value or default


def env_levels(env: Optional[Mapping[str, str]] = None) -> List[int]:
    """Quantize levels from ``QUANTIZE_LEVELS``, or the defaults."""
    value = env_str(ENV_QUANTIZE_LEVELS, None, env)
    return parse_levels(value) if value else list(DEFAULT_QUANTIZE_LEVELS)


def env_pixscale(env: Optional[Mapping[str, str]] = None) -> float:
    """Pixel scale from ``LS_PIXSCALE``, or the default."""
    return float(env_str(ENV_PIXSCALE, str(DEFAULT_PIXSCALE), env))
