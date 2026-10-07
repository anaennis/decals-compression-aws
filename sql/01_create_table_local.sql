-- Manifest written by scripts/run_local.py: one CSV for all cutouts at
-- s3://BUCKET_NAME/manifests/compression_manifest.csv, with a header row.
--
-- Columns are mapped by POSITION, so this list must match
-- decals_compression.core.CSV_FIELDS exactly (same names, same order).
-- `dec` is backticked because DEC is a reserved word in Hive DDL.
-- Empty fields (quantize_level for lossless, rms_over_noise when the noise
-- estimate is 0) read as NULL.
CREATE EXTERNAL TABLE IF NOT EXISTS decals_test.compression_manifest (
  cutout_id        string,
  label            string,
  ra               double,
  `dec`            double,
  layer            string,
  size_pix         int,
  pixscale         double,
  setting          string,
  quantize_level   int,
  size_bytes       bigint,
  pct_of_lossless  double,
  noise_mad        double COMMENT 'MAD-based local noise estimate from adjacent-pixel differences',
  s3_key           string,
  rms_error        double,
  max_abs_error    double,
  rms_over_noise   double
)
ROW FORMAT DELIMITED
  FIELDS TERMINATED BY ','
LOCATION 's3://BUCKET_NAME/manifests/'
TBLPROPERTIES ('skip.header.line.count' = '1');
