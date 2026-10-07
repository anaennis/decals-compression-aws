-- Did the Lambda reproduce the local run? Join the two manifests on
-- (cutout_id, setting) and compare file sizes.
--
-- Expected result for the 7-cutout run: total_pairs = 56, size_matches = 56,
-- missing_in_lambda = 0.
SELECT
  COUNT(*)                                              AS total_pairs,
  COUNT(m.cutout_id)                                    AS present_in_lambda,
  COUNT(*) - COUNT(m.cutout_id)                         AS missing_in_lambda,
  SUM(CASE WHEN l.size_bytes = m.size_bytes THEN 1 ELSE 0 END) AS size_matches,
  MAX(ABS(l.rms_over_noise - m.rms_over_noise))         AS max_rms_over_noise_diff
FROM decals_test.compression_manifest AS l
LEFT JOIN decals_test.compression_manifest_lambda AS m
  ON l.cutout_id = m.cutout_id
 AND l.setting   = m.setting;

-- Row-level view of any mismatches (empty if everything matched).
SELECT
  l.cutout_id, l.setting,
  l.size_bytes AS local_size_bytes,
  m.size_bytes AS lambda_size_bytes
FROM decals_test.compression_manifest AS l
LEFT JOIN decals_test.compression_manifest_lambda AS m
  ON l.cutout_id = m.cutout_id
 AND l.setting   = m.setting
WHERE m.size_bytes IS NULL OR l.size_bytes <> m.size_bytes
ORDER BY l.cutout_id, COALESCE(l.quantize_level, 0);
