"""Feature sets for the three questions the workshop asks, and the splits that keep them honest."""
from __future__ import annotations

import numpy as np
import pandas as pd
from sklearn.model_selection import GroupShuffleSplit

TARGET = "win"
GROUP = "match_id"

# Question 1 - draft: what you know before the game starts.
DRAFT_CAT = ["championName", "teamPosition"]
DRAFT_NUM = ["teamId", "summoner1Id", "summoner2Id"]  # teamId: 100 = blue side, 200 = red side

# Columns that describe how the game ENDED. They give away the winner almost directly.
OUTCOME_LEAKS = [
    "nexusKills", "nexusTakedowns", "nexusLost", "inhibitorKills", "inhibitorTakedowns", "inhibitorsLost",
    "turretsLost", "gameEndedInSurrender", "gameEndedInEarlySurrender", "teamEarlySurrendered",
]
# A score computed from the other columns with a formula. Predicting it is not machine learning.
DERIVED = ["calculated_player_performance"]
IDENTIFIERS = [GROUP, "participantId", "championId", "teamId", "summoner1Id", "summoner2Id",
               "item0", "item1", "item2", "item3", "item4", "item5", "item6"]
TEXT = ["championName", "individualPosition", "lane", "role", "teamPosition"]


def post_game_numeric(df: pd.DataFrame, drop_outcome: bool = True) -> list[str]:
    """Question 2 - post-game player stats (kills, gold, damage, ...)."""
    skip = set(IDENTIFIERS + TEXT + DERIVED + [TARGET])
    if drop_outcome:
        skip |= set(OUTCOME_LEAKS)
    return [c for c in df.columns if c not in skip and pd.api.types.is_numeric_dtype(df[c])]


# Question 3 - by minute: the 18 stats the Live Client API shows for the player you control.
BYMIN_ALL = [
    "magicresist", "healthregenrate", "spellvamp", "timestamp", "maxhealth", "movespeed", "attackdamage",
    "armorpenetrationpercent", "lifesteal", "abilitypower", "resourcevalue", "magicpenetrationflat",
    "attackspeed", "currenthealth", "armor", "magicpenetrationpercent", "resourcemax", "resourceregenrate",
]
# Subset whose units match between the training data and the Live Client API (see lolml/liveclient.py).
BYMIN_LIVE_SAFE = [
    "magicresist", "timestamp", "maxhealth", "movespeed", "attackdamage", "abilitypower",
    "currenthealth", "armor", "resourcemax", "resourcevalue",
]


def group_split(df: pd.DataFrame, test_size: float = 0.2, seed: int = 42, group: str = GROUP):
    """Split so that every match (group) lands entirely in train OR test. Returns (train_idx, test_idx)."""
    gss = GroupShuffleSplit(n_splits=1, test_size=test_size, random_state=seed)
    return next(gss.split(df, groups=df[group]))


def row_split(df: pd.DataFrame, test_size: float = 0.2, seed: int = 42):
    """The naive split: rows are shuffled, so players from one match end up on both sides."""
    rng = np.random.default_rng(seed)
    idx = rng.permutation(len(df))
    n = int(len(df) * test_size)
    return idx[n:], idx[:n]


def accuracy_by_minute(minute: pd.Series, correct: pd.Series, edges=(0, 5, 10, 15, 20, 25, 30, 100)) -> pd.DataFrame:
    b = pd.cut(minute, bins=list(edges), right=False)
    out = correct.groupby(b, observed=True).agg(["mean", "count"])
    out.index = [f"{int(i.left)}-{int(i.right) if i.right < 100 else '+'} min" for i in out.index]
    return out.rename(columns={"mean": "accuracy", "count": "rows"})
