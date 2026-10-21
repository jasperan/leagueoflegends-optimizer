-- 07a_select_ai_remove_acl.sql  -  AUTONOMOUS AI DATABASE ONLY. Run as ADMIN, BEFORE dropping the LOLML user (07b).
-- Removes the network access entry that 03a created. Same region as in 03a:
--   python scripts/db_setup.py 07a        (reads LOLML_GENAI_REGION)

BEGIN
  DBMS_NETWORK_ACL_ADMIN.REMOVE_HOST_ACE(
    host => 'inference.generativeai.&GENAI_REGION..oci.oraclecloud.com',
    ace  => xs$ace_type(privilege_list => xs$name_list('http'),
                        principal_name => 'LOLML',
                        principal_type => xs_acl.ptype_db));
  DBMS_OUTPUT.PUT_LINE('removed host ACE for inference.generativeai.&GENAI_REGION..oci.oraclecloud.com');
END;
/
