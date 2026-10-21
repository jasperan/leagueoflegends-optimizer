# Oracle AI Database 26ai Free in Docker

Use this if you do not have an Autonomous AI Database. Everything in the database part of the workshop works on it
**except Select AI** (scripts `sql/03a_select_ai_acl.sql` and `sql/03b_select_ai_profile.sql` need `DBMS_CLOUD_AI`, which only Autonomous AI Database has).

Needs Docker (Docker Desktop, Colima or Podman) and about 10 GB of disk. The image is multi-arch (amd64 and arm64).

```bash
export ORACLE_PASSWORD='Choose_A_Password_1'          # password of SYS and SYSTEM, kept only in your shell
docker compose -f docker/compose.yaml up -d
docker compose -f docker/compose.yaml logs -f          # Ctrl-C when you see: DATABASE IS READY TO USE!
```

The first start takes a few minutes. The container restarts the database once (to give it vector memory for HNSW
indexes), so wait for the message **after** `01_vector_memory.sh` has finished.

Then, from the `lol-ml-26ai` folder:

```bash
export LOLML_ADMIN_USER=SYSTEM LOLML_ADMIN_PASSWORD="$ORACLE_PASSWORD"
export LOLML_DB_USER=LOLML LOLML_DB_PASSWORD='Choose_Another_Password_1'   # the password the LOLML user will get
export LOLML_DB_DSN=localhost:1521/FREEPDB1
python scripts/db_setup.py        # creates the LOLML user and the tables
python scripts/db_load.py         # loads PLAYER_MATCH and BY_MINUTE_SNAPSHOT
```

Port 1521 busy? `export LOLML_DB_PORT=15210` before `docker compose up` and use `localhost:15210/FREEPDB1` as DSN.

Stop and remove the container **and its data**: `docker compose -f docker/compose.yaml down -v`.
Plain `docker compose ... stop` keeps your tables.

Without Compose, the same thing in one command (no HNSW unless you also run the startdb script by hand; the vector
step then falls back to an IVF index automatically):

```bash
docker run -d --name lolml-oracle-free -p 1521:1521 -e ORACLE_PASSWORD="$ORACLE_PASSWORD" \
  -v lolml_oracle_free_data:/opt/oracle/oradata gvenzl/oracle-free:latest-faststart
```
