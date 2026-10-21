-- 05b_onnx_import.sql  -  run as LOLML after the staging table is filled. Re-runnable (each model is dropped and re-imported).
--
-- Step b: DBMS_DATA_MINING.IMPORT_ONNX_MODEL(model_name, model_data BLOB, metadata JSON) turns the ONNX file into a
-- first-class mining model, scored with the SQL operators PREDICTION and PREDICTION_PROBABILITY. Requires the
-- CREATE MINING MODEL privilege (script 01). The metadata says:
--   function                  classification
--   classificationProbOutput  the ONNX output tensor that holds the class probabilities ("probabilities")
--   labels                    [0, 1]: class 0 = lost, class 1 = won. Without labels the classes are numbered 1..N
--                             and PREDICTION_PROBABILITY(model, 1 ...) would be P(class 0)!
--   input                     maps the single ONNX input tensor "float_input" to table column names, in order.
--                             That is how  USING *  finds the right columns of PLAYER_MATCH / BY_MINUTE_SNAPSHOT.

BEGIN
  FOR s IN (SELECT model_name, onnx_model, metadata FROM onnx_model_stage ORDER BY model_name) LOOP
    BEGIN
      DBMS_DATA_MINING.DROP_MODEL(s.model_name, force => TRUE);
    EXCEPTION WHEN OTHERS THEN NULL;
    END;
    DBMS_DATA_MINING.IMPORT_ONNX_MODEL(s.model_name, s.onnx_model, s.metadata);
    DBMS_OUTPUT.PUT_LINE('imported ONNX model ' || s.model_name);
  END LOOP;
END;
/

SELECT model_name, mining_function, algorithm FROM user_mining_models ORDER BY model_name;
