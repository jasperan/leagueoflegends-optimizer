-- 01_create_user.sql  -  run ONCE as the administrator (ADMIN on Autonomous AI Database, SYSTEM on the Free container).
--
-- Creates the LOLML schema user that owns every workshop object. Safe to re-run: the user is created if it is
-- missing, otherwise its password/grants/quota are simply re-applied.
--
--   python scripts/db_setup.py              (reads LOLML_ADMIN_USER / LOLML_ADMIN_PASSWORD / LOLML_DB_PASSWORD)
--   or in SQL Worksheet / SQLcl:  DEFINE LOLML_PASSWORD=...  then run this file.
--
-- &LOLML_PASSWORD is a substitution variable: the password never lives in this file.
-- Autonomous password rules: 12-30 chars, upper + lower case + a digit, must not contain the user name.

DECLARE
  l_count  NUMBER;
  l_ts     VARCHAR2(128);
  l_pwd    CONSTANT VARCHAR2(200) := '&LOLML_PASSWORD';
BEGIN
  -- Autonomous AI Database keeps user data in tablespace DATA, the Free container in USERS.
  SELECT COUNT(*) INTO l_count FROM dba_tablespaces WHERE tablespace_name = 'DATA';
  l_ts := CASE WHEN l_count > 0 THEN 'DATA' ELSE 'USERS' END;

  SELECT COUNT(*) INTO l_count FROM dba_users WHERE username = 'LOLML';
  IF l_count = 0 THEN
    EXECUTE IMMEDIATE 'CREATE USER lolml IDENTIFIED BY "' || l_pwd || '" DEFAULT TABLESPACE ' || l_ts
                      || ' QUOTA UNLIMITED ON ' || l_ts;
    DBMS_OUTPUT.PUT_LINE('created user LOLML (tablespace ' || l_ts || ')');
  ELSE
    EXECUTE IMMEDIATE 'ALTER USER lolml IDENTIFIED BY "' || l_pwd || '" QUOTA UNLIMITED ON ' || l_ts;
    DBMS_OUTPUT.PUT_LINE('user LOLML already exists: password and quota re-applied (tablespace ' || l_ts || ')');
  END IF;
END;
/

-- DB_DEVELOPER_ROLE exists on Autonomous AI Database AND on 23ai/26ai Free. It bundles CREATE TABLE/VIEW/
-- SEQUENCE/PROCEDURE/TYPE/MINING MODEL/... plus the PL/SQL packages used here (DBMS_VECTOR, DBMS_DATA_MINING).
GRANT CREATE SESSION TO lolml;
GRANT DB_DEVELOPER_ROLE TO lolml;
-- Named explicitly because the ONNX scoring step (script 05) needs it and it is the one people forget.
GRANT CREATE MINING MODEL TO lolml;

-- Autonomous-only extras: Select AI (scripts 03a/03b) and DBMS_CLOUD. On the Free container these packages do not
-- exist, so the GRANT fails with ORA-04042 (seen on Free 23.26.3) or ORA-00942 and the block just says so.
DECLARE
  PROCEDURE try_grant(p_package VARCHAR2) IS
  BEGIN
    EXECUTE IMMEDIATE 'GRANT EXECUTE ON ' || p_package || ' TO lolml';
    DBMS_OUTPUT.PUT_LINE('granted EXECUTE on ' || p_package || ' to LOLML');
  EXCEPTION WHEN OTHERS THEN
    IF SQLCODE IN (-4042, -942) THEN
      DBMS_OUTPUT.PUT_LINE(p_package || ' not present (Free container): skipped');
    ELSE
      RAISE;
    END IF;
  END;
BEGIN
  try_grant('DBMS_CLOUD_AI');
  try_grant('DBMS_CLOUD');
END;
/
