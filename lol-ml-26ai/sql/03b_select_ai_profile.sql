-- 03b_select_ai_profile.sql  -  AUTONOMOUS AI DATABASE ONLY. Run as LOLML after 03a. Re-runnable.
--
-- Select AI turns a plain-English question into SQL over the tables listed in a profile, using an LLM on OCI
-- Generative AI. It needs DBMS_CLOUD_AI, which ships with Autonomous AI Database and is NOT part of the Free
-- container, so there it fails with  PLS-00201: identifier 'DBMS_CLOUD_AI.CREATE_PROFILE' must be declared
-- (observed on 23.26.3.0.0 Free). The Select AI statements themselves could NOT be run by the authors: untested.
--
--   export LOLML_GENAI_KEY=sk-...  LOLML_GENAI_REGION=us-chicago-1  LOLML_GENAI_MODEL=meta.llama-3.3-70b-instruct
--   python scripts/db_setup.py 03        (03a as ADMIN, then this script as LOLML)
--
-- The OCI Generative AI API key (sk-...) is passed through the environment, never written to a file. It is stored as
-- the password of a DBMS_CLOUD credential and sent as a bearer token. The key, the region and the model must match:
-- an API key only works in the region it was created in, and not every model exists in every region.
--
--   &GENAI_KEY     the API key           &GENAI_REGION  region of the key and of the endpoint
--   &GENAI_MODEL   chat model, for example meta.llama-3.3-70b-instruct, xai.grok-3 or openai.gpt-oss-120b
--
-- provider_endpoint is the OpenAI-compatible base URL of OCI Generative AI (documented as
-- https://inference.generativeai.<region>.oci.oraclecloud.com/openai/v1); Select AI adds the /chat/completions path.
-- (An older base, .../20231130/actions/v1, is also documented for API keys; use it if the first one is rejected.)

-- 1. credential: bearer token. The user name is not used by bearer-token endpoints.
BEGIN
  BEGIN
    DBMS_CLOUD.DROP_CREDENTIAL(credential_name => 'LOL_GENAI_CRED');
  EXCEPTION WHEN OTHERS THEN NULL;
  END;
  DBMS_CLOUD.CREATE_CREDENTIAL(
    credential_name => 'LOL_GENAI_CRED',
    username        => 'OPENAI',
    password        => '&GENAI_KEY');
END;
/

-- 2. profile: which provider, model and tables the LLM may see. Table and column comments (script 02) go with it.
BEGIN
  DBMS_CLOUD_AI.DROP_PROFILE(profile_name => 'LOL_GENAI', force => TRUE);
  DBMS_CLOUD_AI.CREATE_PROFILE(
    profile_name => 'LOL_GENAI',
    attributes   => '{"provider": "openai",
                      "credential_name": "LOL_GENAI_CRED",
                      "provider_endpoint": "https://inference.generativeai.&GENAI_REGION..oci.oraclecloud.com/openai/v1",
                      "model": "&GENAI_MODEL",
                      "object_list": [ {"owner": "LOLML", "name": "PLAYER_MATCH"},
                                       {"owner": "LOLML", "name": "BY_MINUTE_SNAPSHOT"} ],
                      "comments": true,
                      "temperature": 0}');
END;
/

SELECT profile_name, status, description FROM user_cloud_ai_profiles ORDER BY profile_name;

-- 3. ask questions. SHOWSQL only returns the SQL the model wrote, RUNSQL also runs it, NARRATE explains the result in
-- words. A model writes the SQL, so the wording can differ from run to run.
SELECT DBMS_CLOUD_AI.GENERATE(
         prompt       => 'Which champion has the highest win rate among champions with at least 500 games?',
         profile_name => 'LOL_GENAI',
         action       => 'showsql') AS generated_sql
FROM dual;

SELECT DBMS_CLOUD_AI.GENERATE(
         prompt       => 'What is the average number of kills, deaths and assists per team position?',
         profile_name => 'LOL_GENAI',
         action       => 'showsql') AS generated_sql
FROM dual;

-- In SQL Worksheet / SQLcl you can also use the SELECT AI shorthand after setting the profile for the session:
--   EXEC DBMS_CLOUD_AI.SET_PROFILE('LOL_GENAI');
--   SELECT AI runsql which champion has the highest win rate among champions with at least 500 games;
--   SELECT AI narrate which top lane champion earns the most gold on average;
--
-- Native OCI route instead of an API key: provider "oci" with credential OCI$RESOURCE_PRINCIPAL needs no key and no
-- network entry (run DBMS_CLOUD_ADMIN.ENABLE_RESOURCE_PRINCIPAL as ADMIN, plus a dynamic group and policy), but
-- needs "region" and "oci_compartment_id" attributes instead of provider_endpoint. See the DBMS_CLOUD_AI documentation.
