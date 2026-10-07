-- Average size (% of lossless) and reconstruction error (in units of the
-- local noise estimate) per compression setting, across all cutouts.
SELECT
  setting,
  ROUND(AVG(pct_of_lossless), 1)  AS avg_pct_size,
  AVG(rms_over_noise)             AS avg_rms_over_noise
FROM decals_test.compression_manifest
GROUP BY setting, quantize_level
ORDER BY COALESCE(quantize_level, 0);
