#!/bin/bash
# HNSW vector indexes live in a dedicated memory area (VECTOR_MEMORY_SIZE). On the Free container it is 0 by
# default, so CREATE VECTOR INDEX ... ORGANIZATION INMEMORY NEIGHBOR GRAPH fails. The parameter can only be raised in
# the root container followed by a restart; this script does that once and is a no-op on later starts.
current=$(sqlplus -s / as sysdba <<'SQL' | tr -d '[:space:]'
set heading off feedback off pagesize 0
select value from v$parameter where name = 'vector_memory_size';
SQL
)
if [ "${current:-0}" = "0" ]; then
  echo "01_vector_memory.sh: setting vector_memory_size=512M and restarting the database"
  sqlplus -s / as sysdba <<'SQL'
alter system set vector_memory_size=512M scope=spfile;
shutdown immediate
startup
alter pluggable database all open;
alter pluggable database all save state;
SQL
else
  echo "01_vector_memory.sh: vector_memory_size already ${current}"
fi
