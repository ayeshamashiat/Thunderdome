"""Tests for the leaderboard extra."""
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from leaderboard import build_leaderboard, format_leaderboard


def write_battle(battles_dir, battle_id, winner, ranking):
    folder = battles_dir / battle_id
    folder.mkdir(parents=True)
    data = {"battle_id": battle_id, "task": "t", "winner": winner,
            "ranking": [{"gladiator": g, "passed": 1, "total": 1} for g in ranking]}
    (folder / "results.json").write_text(json.dumps(data))


def test_counts_wins_and_battles_and_sorts(tmp_path):
    write_battle(tmp_path, "001", "codex-gladiator", ["codex-gladiator", "claude-gladiator"])
    write_battle(tmp_path, "002", "claude-gladiator", ["claude-gladiator", "codex-gladiator"])
    write_battle(tmp_path, "003", "codex-gladiator", ["codex-gladiator", "opencode-gladiator"])
    write_battle(tmp_path, "004", None, ["claude-gladiator", "codex-gladiator"])
    assert build_leaderboard(tmp_path) == [
        {"gladiator": "codex-gladiator", "wins": 2, "battles": 4},
        {"gladiator": "claude-gladiator", "wins": 1, "battles": 3},
        {"gladiator": "opencode-gladiator", "wins": 0, "battles": 1},
    ]


def test_ties_sorted_by_name(tmp_path):
    write_battle(tmp_path, "001", None, ["zeta", "alpha", "mid"])
    rows = build_leaderboard(str(tmp_path))
    assert [r["gladiator"] for r in rows] == ["alpha", "mid", "zeta"]


def test_skips_missing_and_invalid_results(tmp_path):
    (tmp_path / "empty-battle").mkdir()
    bad = tmp_path / "bad-battle"
    bad.mkdir()
    (bad / "results.json").write_text("{not json")
    write_battle(tmp_path, "good", "a", ["a"])
    before = (bad / "results.json").read_text()
    assert build_leaderboard(tmp_path) == [{"gladiator": "a", "wins": 1, "battles": 1}]
    assert (bad / "results.json").read_text() == before


def test_missing_or_empty_dir(tmp_path):
    assert build_leaderboard(tmp_path / "nope") == []
    assert build_leaderboard(tmp_path) == []


def test_format_empty():
    assert format_leaderboard([]) == "No battles scored yet."


def test_format_matches_example():
    rows = [{"gladiator": "codex-gladiator", "wins": 2, "battles": 3},
            {"gladiator": "claude-gladiator", "wins": 1, "battles": 3}]
    assert format_leaderboard(rows) == (
        "Rank  Gladiator           Wins  Battles\n"
        "1     codex-gladiator     2     3\n"
        "2     claude-gladiator    1     3"
    )


def test_format_aligns_long_names():
    rows = [{"gladiator": "a-really-long-gladiator-name", "wins": 10, "battles": 12},
            {"gladiator": "b", "wins": 0, "battles": 1}]
    lines = format_leaderboard(rows).split("\n")
    name_column = lines[0].index("Gladiator")
    assert lines[1].index("a-really") == name_column
    assert lines[2][name_column] == "b"
    assert lines[1].split() == ["1", "a-really-long-gladiator-name", "10", "12"]
    assert lines[0].split() == ["Rank", "Gladiator", "Wins", "Battles"]
