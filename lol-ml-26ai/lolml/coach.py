"""Post-game "AI coach": percentile bands from the dataset + the model's win probability -> a prompt for an LLM.

Only the prompt builder and the percentile maths are tested against real data. The model call goes to the OCI
Generative AI Chat Completions REST endpoint with an API key
(https://docs.oracle.com/en-us/iaas/Content/generative-ai/api-keys.htm); it needs your own key.
Environment: LOLML_GENAI_KEY (the sk-... secret), LOLML_GENAI_REGION (default us-chicago-1),
LOLML_GENAI_MODEL (default xai.grok-3; any chat model your region lists, for example meta.llama-3.3-70b-instruct).
This is post-game analysis on purpose: it never reads a running game.
"""
from __future__ import annotations

import os

import pandas as pd
import requests

STATS = {  # label -> (numerator expression, higher_is_better)
    "deaths per minute": ("deaths", False),
    "kills + assists per minute": ("ka", True),
    "gold per minute": ("goldEarned", True),
    "damage to champions per minute": ("totalDamageDealtToChampions", True),
    "minions killed per minute": ("totalMinionsKilled", True),
    "vision score per minute": ("visionScore", True),
}


def per_minute(df: pd.DataFrame) -> pd.DataFrame:
    """The six per-minute stats the coach talks about."""
    m = df["duration"].clip(lower=1)
    out = pd.DataFrame(index=df.index)
    for label, (col, _) in STATS.items():
        out[label] = (df["kills"] + df["assists"] if col == "ka" else df[col]) / m
    out["position"] = df["teamPosition"]
    return out


def percentile_report(row: pd.Series, reference: pd.DataFrame) -> list[dict]:
    """Where does this player-game sit among players in the same position? percentile 90 = better than 90 % of them (for deaths, fewer is better)."""
    ref_pm = per_minute(reference)
    me = per_minute(row.to_frame().T.astype({"duration": float, "kills": float, "assists": float, "deaths": float,
                                              "goldEarned": float, "totalDamageDealtToChampions": float,
                                              "totalMinionsKilled": float, "visionScore": float})).iloc[0]
    ref_pm = ref_pm[ref_pm["position"] == me["position"]]
    rows = []
    for label, (_, higher_better) in STATS.items():
        pct = float((ref_pm[label] < me[label]).mean() * 100)
        rows.append({"stat": label, "value": round(float(me[label]), 2), "percentile": round(pct if higher_better else 100 - pct)})
    return rows


def build_messages(champion: str, position: str, minutes: float, won: bool, model_win_probability: float, report: list[dict]) -> list[dict]:
    table = "\n".join(f"- {r['stat']}: {r['value']} (better than {r['percentile']} % of {position} players)" for r in report)
    system = ("You are a concise League of Legends coach. Use ONLY the numbers you are given. Do not invent events, "
              "items or objectives that are not in the data. Reply with a two-sentence summary and exactly three bullet points "
              "of advice, most important first.")
    user = (f"Game: {champion} ({position}), {minutes:.0f} minutes, result: {'win' if won else 'loss'}.\n"
            f"A statistical model that sees the final stats gave this player's team a {model_win_probability:.0%} chance of winning.\n"
            f"Per-minute stats against other {position} players:\n{table}")
    return [{"role": "system", "content": system}, {"role": "user", "content": user}]


def endpoint(region: str | None = None) -> str:
    region = region or os.environ.get("LOLML_GENAI_REGION", "us-chicago-1")
    return f"https://inference.generativeai.{region}.oci.oraclecloud.com/20231130/actions/v1/chat/completions"


def ask(messages: list[dict], url: str | None = None, model: str | None = None, key: str | None = None, timeout: int = 60) -> str:
    key = key or os.environ.get("LOLML_GENAI_KEY")
    if not key:
        raise RuntimeError("Set LOLML_GENAI_KEY to your OCI Generative AI API key (Lab 9 explains how to create one).")
    r = requests.post(url or endpoint(), timeout=timeout, headers={"Authorization": f"Bearer {key}"},
                      json={"model": model or os.environ.get("LOLML_GENAI_MODEL", "xai.grok-3"), "messages": messages, "temperature": 0.2})
    r.raise_for_status()
    return r.json()["choices"][0]["message"]["content"]
