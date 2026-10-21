-- 06_cleanup.sql  -  run as LOLML. Drops everything the workshop created in the LOLML schema. Re-runnable.
-- To remove the user itself as well, run 07b_drop_user.sql as ADMIN / SYSTEM (and 07a first if you used Select AI).

-- Select AI profile (Autonomous only; ignored elsewhere)
BEGIN
  EXECUTE IMMEDIATE 'BEGIN DBMS_CLOUD_AI.DROP_PROFILE(profile_name => ''LOL_GENAI'', force => TRUE); END;';
EXCEPTION WHEN OTHERS THEN NULL;
END;
/

-- Select AI credential (Autonomous only; ignored elsewhere)
BEGIN
  EXECUTE IMMEDIATE 'BEGIN DBMS_CLOUD.DROP_CREDENTIAL(credential_name => ''LOL_GENAI_CRED''); END;';
EXCEPTION WHEN OTHERS THEN NULL;
END;
/

-- ONNX models
BEGIN
  FOR m IN (SELECT model_name FROM user_mining_models WHERE model_name LIKE 'LOL%') LOOP
    DBMS_DATA_MINING.DROP_MODEL(m.model_name, force => TRUE);
    DBMS_OUTPUT.PUT_LINE('dropped model ' || m.model_name);
  END LOOP;
END;
/

DROP TABLE IF EXISTS onnx_model_stage PURGE;
DROP TABLE IF EXISTS player_game_vector PURGE;   -- also drops its vector index
DROP TABLE IF EXISTS vector_norm PURGE;
DROP TABLE IF EXISTS by_minute_snapshot PURGE;
DROP TABLE IF EXISTS player_match PURGE;
