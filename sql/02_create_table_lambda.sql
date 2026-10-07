-- Manifests written by the Lambda: one CSV per cutout at
-- s3://BUCKET_NAME/manifests-lambda/<cutout_id>.csv, each with a header row.
-- Same schema and column order as decals_test.compression_manifest.
CREATE EXTERNAL TABLE IF NOT EXISTS decals_test.compression_manifest_lambda (
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
LOCATION 's3://BUCKET_NAME/manifests-lambda/'
TBLPROPERTIES ('skip.header.line.count' = '1');
