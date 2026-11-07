"""Tests for reading and sorting battle history."""

import json

from extras.history.history import battle_history


def test_returns_ids_and_winners_newest_first(tmp_path):
    for battle_id, winner in [("001-alpha", "claude"), ("003-gamma", None), ("002-beta", "codex")]:
        battle_dir = tmp_path / battle_id
        battle_dir.mkdir()
        result = {"battle_id": battle_id, "winner": winner, "ranking": []}
        (battle_dir / "results.json").write_text(json.dumps(result), encoding="utf-8")

    assert battle_history(tmp_path) == [
        {"battle_id": "003-gamma", "winner": None},
        {"battle_id": "002-beta", "winner": "codex"},
        {"battle_id": "001-alpha", "winner": "claude"},
    ]


def test_skips_missing_invalid_and_loose_results(tmp_path):
    (tmp_path / "unscored").mkdir()
    (tmp_path / "loose.json").write_text("{}", encoding="utf-8")
    invalid = tmp_path / "invalid"
    invalid.mkdir()
    (invalid / "results.json").write_text("not json", encoding="utf-8")
    missing_id = tmp_path / "missing-id"
    missing_id.mkdir()
    (missing_id / "results.json").write_text("{}", encoding="utf-8")

    assert battle_history(tmp_path) == []
    assert battle_history(tmp_path / "missing") == []


def test_missing_winner_is_none(tmp_path):
    battle_dir = tmp_path / "001-test"
    battle_dir.mkdir()
    (battle_dir / "results.json").write_text('{"battle_id":"001-test"}', encoding="utf-8")
    assert battle_history(str(tmp_path)) == [{"battle_id": "001-test", "winner": None}]
