-- 02_tables.sql  -  run as LOLML. Re-runnable (CREATE TABLE IF NOT EXISTS, COMMENT ON overwrites).
--
-- Two relational tables mirror the workshop datasets. Data arrives with scripts/db_load.py.
-- The COMMENTs matter: Select AI (script 03) sends table and column comments to the LLM so that it can
-- translate "which champion wins most" into correct SQL.

-- -------------------------------------------------------------------------------------------------------------
-- PLAYER_MATCH: one row per player per match (10 rows per match), the post-game stats of data/performance.parquet.
-- A ~30 column relational subset of the 98 parquet columns.
-- -------------------------------------------------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS player_match (
  player_match_id                    NUMBER(10)    NOT NULL,
  match_id                           NUMBER(15)    NOT NULL,
  champion_name                      VARCHAR2(30)  NOT NULL,
  team_position                      VARCHAR2(10),
  team_id                            NUMBER(3),
  win                                NUMBER(1)     NOT NULL,
  duration_min                       NUMBER(6,2),
  kills                              NUMBER(3),
  deaths                             NUMBER(3),
  assists                            NUMBER(3),
  champ_level                        NUMBER(2),
  gold_earned                        NUMBER(7),
  gold_spent                         NUMBER(7),
  total_damage_dealt_to_champions    NUMBER(8),
  total_damage_taken                 NUMBER(8),
  damage_dealt_to_objectives         NUMBER(8),
  damage_dealt_to_turrets            NUMBER(8),
  total_minions_killed               NUMBER(4),
  neutral_minions_killed             NUMBER(4),
  vision_score                       NUMBER(4),
  detector_wards_placed              NUMBER(4),
  time_ccing_others                  NUMBER(5),
  total_heals_on_teammates           NUMBER(8),
  total_damage_shielded_on_teammates NUMBER(8),
  total_time_spent_dead              NUMBER(6),
  largest_killing_spree              NUMBER(3),
  largest_multi_kill                 NUMBER(2),
  double_kills                       NUMBER(3),
  first_blood_kill                   NUMBER(1),
  dragon_kills                       NUMBER(2),
  baron_kills                        NUMBER(2),
  CONSTRAINT player_match_pk PRIMARY KEY (player_match_id),
  CONSTRAINT player_match_win_ck CHECK (win IN (0, 1))
);

COMMENT ON TABLE player_match IS 'One row per player per League of Legends match (10 rows per match): post-game statistics of ranked solo queue games. WIN = 1 if the player''s team won.';
COMMENT ON COLUMN player_match.player_match_id IS 'Surrogate key (row number in the source file).';
COMMENT ON COLUMN player_match.match_id IS 'Numeric Riot match id. All 10 players of a game share it. Never split one match across train and test.';
COMMENT ON COLUMN player_match.champion_name IS 'Name of the champion the player used, for example Ahri or Lee Sin style names without spaces (LeeSin).';
COMMENT ON COLUMN player_match.team_position IS 'Assigned lane or role: TOP, JUNGLE, MIDDLE, BOTTOM (the ADC) or UTILITY (the support). NULL when Riot could not assign one.';
COMMENT ON COLUMN player_match.team_id IS 'Side of the map: 100 = blue side, 200 = red side.';
COMMENT ON COLUMN player_match.win IS 'Target label: 1 if the player''s team won the game, 0 if it lost. Win rate = AVG(win).';
COMMENT ON COLUMN player_match.duration_min IS 'Game length in minutes.';
COMMENT ON COLUMN player_match.kills IS 'Enemy champions this player killed.';
COMMENT ON COLUMN player_match.deaths IS 'Number of times this player died.';
COMMENT ON COLUMN player_match.assists IS 'Enemy champion kills this player assisted.';
COMMENT ON COLUMN player_match.champ_level IS 'Champion level at the end of the game (1-18).';
COMMENT ON COLUMN player_match.gold_earned IS 'Total gold earned during the game.';
COMMENT ON COLUMN player_match.gold_spent IS 'Total gold spent in the shop.';
COMMENT ON COLUMN player_match.total_damage_dealt_to_champions IS 'Total damage (physical + magic + true) dealt to enemy champions.';
COMMENT ON COLUMN player_match.total_damage_taken IS 'Total damage this player received.';
COMMENT ON COLUMN player_match.damage_dealt_to_objectives IS 'Damage dealt to objectives such as dragon, baron and turrets.';
COMMENT ON COLUMN player_match.damage_dealt_to_turrets IS 'Damage dealt to enemy turrets.';
COMMENT ON COLUMN player_match.total_minions_killed IS 'Lane minions killed (creep score from lanes).';
COMMENT ON COLUMN player_match.neutral_minions_killed IS 'Jungle monsters killed.';
COMMENT ON COLUMN player_match.vision_score IS 'Riot vision score: wards placed, wards cleared and enemy vision denied.';
COMMENT ON COLUMN player_match.detector_wards_placed IS 'Control wards placed.';
COMMENT ON COLUMN player_match.time_ccing_others IS 'Seconds of crowd control (stuns, slows, ...) applied to enemies.';
COMMENT ON COLUMN player_match.total_heals_on_teammates IS 'Healing done to teammates.';
COMMENT ON COLUMN player_match.total_damage_shielded_on_teammates IS 'Damage absorbed by shields this player gave to teammates.';
COMMENT ON COLUMN player_match.total_time_spent_dead IS 'Seconds spent dead, waiting to respawn.';
COMMENT ON COLUMN player_match.largest_killing_spree IS 'Most kills in a row without dying.';
COMMENT ON COLUMN player_match.largest_multi_kill IS 'Largest multi kill: 1 single, 2 double, 3 triple, 4 quadra, 5 penta.';
COMMENT ON COLUMN player_match.double_kills IS 'Number of double kills.';
COMMENT ON COLUMN player_match.first_blood_kill IS '1 if this player drew first blood of the game.';
COMMENT ON COLUMN player_match.dragon_kills IS 'Dragons this player personally killed.';
COMMENT ON COLUMN player_match.baron_kills IS 'Baron Nashors this player personally killed.';

-- Handy for "win rate by champion" style questions; also what Select AI is pointed at.
CREATE INDEX IF NOT EXISTS player_match_champ_ix ON player_match (champion_name, team_position);
CREATE INDEX IF NOT EXISTS player_match_match_ix ON player_match (match_id);

-- -------------------------------------------------------------------------------------------------------------
-- BY_MINUTE_SNAPSHOT: one row per player per minute mark: the stats the Live Client API shows for the player you
-- control, with the final result of the game attached (data/by_minute.parquet, ~1M rows, ~3.5k matches).
-- -------------------------------------------------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS by_minute_snapshot (
  snapshot_id                 NUMBER(10)   NOT NULL,
  match_id                    VARCHAR2(30) NOT NULL,
  slot                        NUMBER(2)    NOT NULL,
  winner                      NUMBER(1)    NOT NULL,
  game_minute                 NUMBER(10,5),
  timestamp_ms                NUMBER(10),
  magic_resist                NUMBER(5),
  health_regen_rate           NUMBER(6),
  spell_vamp                  NUMBER(4),
  bonus_armor_pen_percent     NUMBER(4),
  bonus_magic_pen_percent     NUMBER(4),
  max_health                  NUMBER(6),
  move_speed                  NUMBER(5),
  attack_damage               NUMBER(5),
  armor_pen_percent           NUMBER(4),
  life_steal                  NUMBER(4),
  ability_power               NUMBER(6),
  cooldown_reduction          NUMBER(4),
  resource_value              NUMBER(6),
  magic_pen_flat              NUMBER(4),
  attack_speed                NUMBER(5),
  current_health              NUMBER(6),
  armor                       NUMBER(5),
  magic_pen_percent           NUMBER(4),
  armor_pen_flat              NUMBER(4),
  resource_max                NUMBER(6),
  resource_regen_rate         NUMBER(6),
  CONSTRAINT by_minute_snapshot_pk PRIMARY KEY (snapshot_id),
  CONSTRAINT by_minute_winner_ck CHECK (winner IN (0, 1))
);

COMMENT ON TABLE by_minute_snapshot IS 'In-game snapshots: one row per player (SLOT 1-10) roughly every minute of a League of Legends match, with the final outcome of that player''s team in WINNER. Used for live win-probability models.';
COMMENT ON COLUMN by_minute_snapshot.snapshot_id IS 'Surrogate key (row number in the source file).';
COMMENT ON COLUMN by_minute_snapshot.match_id IS 'Riot match id including the region prefix, for example EUW1_2284630300.';
COMMENT ON COLUMN by_minute_snapshot.slot IS 'Player slot in the match: 1-5 = one team, 6-10 = the other team.';
COMMENT ON COLUMN by_minute_snapshot.winner IS 'Final result of the game for this slot''s team: 1 = this team won, 0 = lost. Same value for all snapshots of a slot.';
COMMENT ON COLUMN by_minute_snapshot.game_minute IS 'Game time of the snapshot in minutes (fractional).';
COMMENT ON COLUMN by_minute_snapshot.timestamp_ms IS 'Game time of the snapshot in milliseconds.';
COMMENT ON COLUMN by_minute_snapshot.magic_resist IS 'Magic resistance stat at the snapshot.';
COMMENT ON COLUMN by_minute_snapshot.health_regen_rate IS 'Health regeneration stat at the snapshot (the unit differs from the Live Client API).';
COMMENT ON COLUMN by_minute_snapshot.spell_vamp IS 'Spell vamp stat (percent) at the snapshot.';
COMMENT ON COLUMN by_minute_snapshot.bonus_armor_pen_percent IS 'Bonus armor penetration percent (always 0 in this dataset).';
COMMENT ON COLUMN by_minute_snapshot.bonus_magic_pen_percent IS 'Bonus magic penetration percent (always 0 in this dataset).';
COMMENT ON COLUMN by_minute_snapshot.max_health IS 'Maximum health at the snapshot.';
COMMENT ON COLUMN by_minute_snapshot.move_speed IS 'Movement speed at the snapshot.';
COMMENT ON COLUMN by_minute_snapshot.attack_damage IS 'Attack damage at the snapshot.';
COMMENT ON COLUMN by_minute_snapshot.armor_pen_percent IS 'Armor penetration percent at the snapshot.';
COMMENT ON COLUMN by_minute_snapshot.life_steal IS 'Life steal percent at the snapshot.';
COMMENT ON COLUMN by_minute_snapshot.ability_power IS 'Ability power at the snapshot.';
COMMENT ON COLUMN by_minute_snapshot.cooldown_reduction IS 'Cooldown reduction (always 0 in this dataset).';
COMMENT ON COLUMN by_minute_snapshot.resource_value IS 'Current resource (mana, energy, ...) at the snapshot.';
COMMENT ON COLUMN by_minute_snapshot.magic_pen_flat IS 'Flat magic penetration at the snapshot.';
COMMENT ON COLUMN by_minute_snapshot.attack_speed IS 'Attack speed stat at the snapshot (percent style units).';
COMMENT ON COLUMN by_minute_snapshot.current_health IS 'Current health at the snapshot.';
COMMENT ON COLUMN by_minute_snapshot.armor IS 'Armor at the snapshot.';
COMMENT ON COLUMN by_minute_snapshot.magic_pen_percent IS 'Magic penetration percent at the snapshot.';
COMMENT ON COLUMN by_minute_snapshot.armor_pen_flat IS 'Flat armor penetration (always 0 in this dataset).';
COMMENT ON COLUMN by_minute_snapshot.resource_max IS 'Maximum resource (mana, energy, ...) at the snapshot.';
COMMENT ON COLUMN by_minute_snapshot.resource_regen_rate IS 'Resource regeneration stat at the snapshot.';

CREATE INDEX IF NOT EXISTS by_minute_match_ix ON by_minute_snapshot (match_id);
