-- 04_vector.sql  -  run as LOLML. Re-runnable.
--
-- "Games like this": every player-game becomes a point in a 12-dimensional space built from per-minute
-- performance (kills, deaths, assists, gold, damage, CS, vision, ... divided by game length, then z-scored).
-- Games with a similar playstyle end up close together, whatever champion or game length they had.
--
-- The embedding is computed in Python (lolml.db.embed). The z-score needs the SAME mean and standard deviation for
-- a new game as for the stored ones, so they are kept in VECTOR_NORM next to the vectors. Only the first 95% of
-- matches are stored; the rest are "new games" (lolml.db.is_holdout) that you embed and search with.
--
-- Works on Oracle AI Database 26ai Free and Autonomous AI Database (VECTOR data type, VECTOR_DISTANCE).
-- Fill the tables with: python scripts/db_vectors.py   (that also runs 04b_vector_index.sql afterwards).

CREATE TABLE IF NOT EXISTS vector_norm (
  feature_order NUMBER(3)    NOT NULL,
  feature_name  VARCHAR2(40) NOT NULL,
  mean_value    BINARY_DOUBLE NOT NULL,
  std_value     BINARY_DOUBLE NOT NULL,
  CONSTRAINT vector_norm_pk PRIMARY KEY (feature_order)
);
COMMENT ON TABLE vector_norm IS 'Mean and standard deviation used to z-score each embedding dimension. Apply the same values to any new game before searching.';

CREATE TABLE IF NOT EXISTS player_game_vector (
  player_match_id NUMBER(10) NOT NULL,
  embedding       VECTOR(12, FLOAT32) NOT NULL,
  CONSTRAINT player_game_vector_pk PRIMARY KEY (player_match_id),
  -- Not enforced: it documents the join for Select AI and keeps TRUNCATE of PLAYER_MATCH possible.
  CONSTRAINT player_game_vector_fk FOREIGN KEY (player_match_id) REFERENCES player_match (player_match_id) DISABLE NOVALIDATE
);
COMMENT ON TABLE player_game_vector IS 'Playstyle embedding (12 z-scored per-minute stats) of each player-game in PLAYER_MATCH, for similarity search with VECTOR_DISTANCE.';
COMMENT ON COLUMN player_game_vector.embedding IS 'Order: KILLS_PM, DEATHS_PM, ASSISTS_PM, GOLD_PM, DAMAGE_PM, DAMAGE_TAKEN_PM, CS_PM, VISION_PM, OBJECTIVE_DAMAGE_PM, TURRET_DAMAGE_PM, CC_TIME_PM, HEAL_SHIELD_PM.';
