-- 07b_drop_user.sql  -  run as the administrator (ADMIN, or SYSTEM on the Free container). Re-runnable.
-- Drops the LOLML user with everything it owns. Close every other session of LOLML first (notebooks, servers),
-- otherwise Oracle answers ORA-01940: cannot drop a user that is currently connected.
--   python scripts/db_setup.py 07b

BEGIN
  FOR u IN (SELECT username FROM dba_users WHERE username = 'LOLML') LOOP
    EXECUTE IMMEDIATE 'DROP USER lolml CASCADE';
    DBMS_OUTPUT.PUT_LINE('dropped user LOLML');
  END LOOP;
END;
/

SELECT COUNT(*) AS lolml_users_left FROM dba_users WHERE username = 'LOLML';
