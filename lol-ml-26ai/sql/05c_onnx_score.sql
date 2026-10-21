-- 05c_onnx_score.sql  -  run as LOLML after 05b. Pure SQL: the model runs next to the data, no rows leave the database.
--
-- Hold-out matches (the ones the model never saw in training) are MOD(match_id, 20) = 7, the same rule as
-- lolml.db.is_holdout. PREDICTION returns the label 0/1, PREDICTION_PROBABILITY(model, 1 ...) is P(win).

-- 1. Accuracy of the post-game model on hold-out games, computed entirely in SQL.
SELECT COUNT(*)                                                                   AS games,
       ROUND(AVG(CASE WHEN PREDICTION(lol_win_postgame USING *) = win THEN 1 ELSE 0 END), 4) AS accuracy
FROM   player_match
WHERE  MOD(match_id, 20) = 7;

-- 2. One hold-out match, player by player: predicted win probability next to what really happened.
SELECT champion_name, team_position, team_id,
       kills || '/' || deaths || '/' || assists                                  AS kda,
       ROUND(PREDICTION_PROBABILITY(lol_win_postgame, 1 USING *), 3)              AS p_win,
       win
FROM   player_match
WHERE  match_id = (SELECT MIN(match_id) FROM player_match WHERE MOD(match_id, 20) = 7)
ORDER  BY team_id, team_position;

-- 3. Score and aggregate in one statement: which champions look most winning in the hold-out games?
SELECT champion_name, COUNT(*) AS games,
       ROUND(AVG(PREDICTION_PROBABILITY(lol_win_postgame, 1 USING *)), 3) AS avg_p_win,
       ROUND(AVG(win), 3)                                                  AS actual_win_rate
FROM   player_match
WHERE  MOD(match_id, 20) = 7
GROUP  BY champion_name
HAVING COUNT(*) >= 60
ORDER  BY avg_p_win DESC
FETCH FIRST 5 ROWS ONLY;

-- 4. The live-safe model on in-game snapshots: accuracy by game time (it only improves as the game goes on).
--    Needs the second model: python scripts/export_onnx.py --model live, then python scripts/db_score.py --model live
SELECT FLOOR(game_minute / 5) * 5 AS from_minute,
       COUNT(*)                   AS snapshots,
       ROUND(AVG(CASE WHEN PREDICTION(lol_win_live USING *) = winner THEN 1 ELSE 0 END), 3) AS accuracy
FROM   by_minute_snapshot
WHERE  MOD(TO_NUMBER(SUBSTR(match_id, INSTR(match_id, '_') + 1)), 20) = 7
GROUP  BY FLOOR(game_minute / 5) * 5
ORDER  BY from_minute;

-- 5. A hypothetical game that is not in any table: list every model input with USING <expr> AS <column>.
SELECT ROUND(PREDICTION_PROBABILITY(lol_win_live, 1
         USING 900000 AS timestamp_ms, 2400 AS max_health, 2400 AS current_health, 345 AS move_speed,
               120 AS attack_damage, 60 AS ability_power, 90 AS armor, 60 AS magic_resist,
               400 AS resource_value, 600 AS resource_max), 3) AS p_win_example
FROM   dual;
