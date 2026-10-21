-- 03a_select_ai_acl.sql  -  AUTONOMOUS AI DATABASE ONLY. Run once as ADMIN. Re-runnable.
--
-- The database blocks outbound network calls by default. Select AI reaches OCI Generative AI through its
-- OpenAI-compatible endpoint (provider "openai"), so the LOLML user needs a network access entry for that host.
--
--   python scripts/db_setup.py 03a        (reads LOLML_GENAI_REGION, runs as ADMIN)
--
-- &GENAI_REGION is the OCI region of your Generative AI API key, for example us-chicago-1.

BEGIN
  DBMS_NETWORK_ACL_ADMIN.APPEND_HOST_ACE(
    host => 'inference.generativeai.&GENAI_REGION..oci.oraclecloud.com',
    ace  => xs$ace_type(privilege_list => xs$name_list('http'),
                        principal_name => 'LOLML',
                        principal_type => xs_acl.ptype_db));
  DBMS_OUTPUT.PUT_LINE('host ACE present for inference.generativeai.&GENAI_REGION..oci.oraclecloud.com');
END;
/

-- Check: the host must be listed for LOLML.
SELECT host, principal FROM dba_host_aces WHERE host LIKE 'inference.generativeai.%' ORDER BY host, principal;
