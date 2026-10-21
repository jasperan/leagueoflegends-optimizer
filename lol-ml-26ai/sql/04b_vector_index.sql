-- 04b_vector_index.sql  -  run as LOLML after PLAYER_GAME_VECTOR is filled (scripts/db_vectors.py does it). Re-runnable.
--
-- Approximate nearest-neighbour index on the embedding, COSINE distance.
--   HNSW  an in-memory neighbour graph. Fast and accurate, but needs vector memory: Autonomous AI Database has it,
--         the Free container needs ALTER SYSTEM SET vector_memory_size=512M in the root container and a restart
--         (docker/ does this for you).
--   IVF   an on-disk partitioned index. Needs no vector memory. Used automatically if HNSW cannot be created.
-- The block prints which one you got.

BEGIN
  EXECUTE IMMEDIATE 'DROP INDEX IF EXISTS player_game_vec_hnsw';
  EXECUTE IMMEDIATE 'DROP INDEX IF EXISTS player_game_vec_ivf';
  BEGIN
    EXECUTE IMMEDIATE 'CREATE VECTOR INDEX player_game_vec_hnsw ON player_game_vector (embedding)
                       ORGANIZATION INMEMORY NEIGHBOR GRAPH DISTANCE COSINE WITH TARGET ACCURACY 95
                       PARAMETERS (TYPE HNSW, NEIGHBORS 32, EFCONSTRUCTION 200)';
    DBMS_OUTPUT.PUT_LINE('created HNSW vector index player_game_vec_hnsw');
  EXCEPTION WHEN OTHERS THEN
    DBMS_OUTPUT.PUT_LINE('HNSW not available (' || SUBSTR(SQLERRM, 1, 160) || ')');
    EXECUTE IMMEDIATE 'CREATE VECTOR INDEX player_game_vec_ivf ON player_game_vector (embedding)
                       ORGANIZATION NEIGHBOR PARTITIONS DISTANCE COSINE WITH TARGET ACCURACY 90
                       PARAMETERS (TYPE IVF, NEIGHBOR PARTITIONS 100)';
    DBMS_OUTPUT.PUT_LINE('created IVF vector index player_game_vec_ivf instead');
  END;
END;
/

-- Games like this: the 5 player-games closest to one stored game (player_match_id from the table).
-- From Python you bind the embedding of a NEW game instead of the subquery (see scripts/db_similar.py).
-- FETCH APPROX lets the optimizer use the vector index; use FETCH FIRST 5 ROWS ONLY for an exact scan.
WITH q AS (SELECT embedding FROM player_game_vector WHERE player_match_id = (SELECT MIN(player_match_id) FROM player_game_vector))
SELECT pm.champion_name,
       pm.team_position,
       pm.win,
       pm.kills || '/' || pm.deaths || '/' || pm.assists                               AS kda,
       ROUND(VECTOR_DISTANCE(v.embedding, q.embedding, COSINE), 4)                     AS cosine_distance
FROM   player_game_vector v
JOIN   player_match pm ON pm.player_match_id = v.player_match_id
CROSS JOIN q
ORDER  BY VECTOR_DISTANCE(v.embedding, q.embedding, COSINE)
FETCH APPROX FIRST 6 ROWS ONLY;
