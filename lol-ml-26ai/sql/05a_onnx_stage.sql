-- 05a_onnx_stage.sql  -  run as LOLML. Re-runnable.
--
-- In-database scoring with an ONNX model trained OUTSIDE the database (scikit-learn -> scripts/export_onnx.py).
-- Step a: a staging table that holds the .onnx file as a BLOB plus the import metadata.
--   scripts/db_score.py fills it from $LOLML_HOME/models/*.onnx. On Autonomous AI Database you can also pull the
--   file from Object Storage straight into the table, no client involved:
--
--   INSERT INTO onnx_model_stage (model_name, onnx_model, metadata)
--   VALUES ('LOL_WIN_POSTGAME',
--           DBMS_CLOUD.GET_OBJECT(credential_name => 'OBJ_STORE_CRED',
--                                 object_uri      => 'https://objectstorage.<region>.oraclecloud.com/n/<ns>/b/<bucket>/o/lol_win_postgame.onnx'),
--           JSON('<contents of the "import_metadata" field in lol_win_postgame.json>'));

CREATE TABLE IF NOT EXISTS onnx_model_stage (
  model_name VARCHAR2(128) NOT NULL,
  onnx_model BLOB          NOT NULL,
  metadata   JSON          NOT NULL,
  staged_at  TIMESTAMP DEFAULT SYSTIMESTAMP,
  CONSTRAINT onnx_model_stage_pk PRIMARY KEY (model_name)
);
COMMENT ON TABLE onnx_model_stage IS 'ONNX files waiting to be imported with DBMS_DATA_MINING.IMPORT_ONNX_MODEL, plus the JSON import metadata (input column names, labels).';
