"""Tests for token counting. Fake logs use the same formats as the real ones."""

import json
import re
import sqlite3
from datetime import datetime, timezone

from judge import rank
from tokens import claude_fresh_tokens, codex_fresh_tokens, opencode_fresh_tokens

START = datetime(2026, 11, 4, 14, 20, tzinfo=timezone.utc)
END = datetime(2026, 11, 4, 14, 30, tzinfo=timezone.utc)
BEFORE, DURING, AFTER = "2026-11-04T14:10:00Z", "2026-11-04T14:25:00Z", "2026-11-04T14:40:00Z"
AGENT_DIR = "/home/me/Thunderdome/arena/some-gladiator"


# ─────────────── Claude Code ───────────────

def claude_line(timestamp, message_id, input_t, cache_write, cache_read, output):
    usage = {"input_tokens": input_t, "cache_creation_input_tokens": cache_write,
             "cache_read_input_tokens": cache_read, "output_tokens": output}
    return json.dumps({"timestamp": timestamp, "message": {"id": message_id, "usage": usage}})


def test_claude_counts_fresh_tokens_once_per_message(tmp_path):
    folder = tmp_path / re.sub(r"[^a-zA-Z0-9]", "-", AGENT_DIR)
    folder.mkdir()
    (folder / "session.jsonl").write_text("\n".join([
        claude_line(BEFORE, "m0", 5, 500, 0, 50),        # before the battle: ignored
        claude_line(DURING, "m1", 2, 100, 9999, 10),     # cache reads (9999) don't count
        claude_line(DURING, "m1", 2, 100, 9999, 10),     # same reply logged twice: counted once
        claude_line(DURING, "m2", 1, 0, 9999, 20),
        claude_line(AFTER, "m3", 5, 500, 0, 50),         # after the last commit: ignored
    ]))

    assert claude_fresh_tokens(AGENT_DIR, START, END, projects_dir=tmp_path) == (2 + 100 + 10) + (1 + 0 + 20)


def test_claude_without_logs_is_unknown(tmp_path):
    assert claude_fresh_tokens(AGENT_DIR, START, END, projects_dir=tmp_path) is None


# ─────────────── Codex ───────────────

def codex_event(timestamp, input_t, cached, output):
    usage = {"input_tokens": input_t, "cached_input_tokens": cached, "output_tokens": output}
    return json.dumps({"timestamp": timestamp, "type": "event_msg",
                       "payload": {"type": "token_count", "info": {"total_token_usage": usage}}})


def test_codex_uses_running_total_difference(tmp_path):
    rollout = tmp_path / "s1" / "sessions" / "rollout-1.jsonl"
    rollout.parent.mkdir(parents=True)
    rollout.write_text("\n".join([
        json.dumps({"type": "session_meta", "payload": {"cwd": AGENT_DIR}}),
        codex_event(BEFORE, 1000, 200, 50),     # running total before: 1000-200+50 = 850
        codex_event(DURING, 5000, 3000, 300),   # 2300
        codex_event(DURING, 5000, 3000, 300),   # repeated event: no double counting
        codex_event(DURING, 9000, 6000, 500),   # 3500 at the last commit
        codex_event(AFTER, 20000, 9000, 900),   # after: ignored
    ]))

    assert codex_fresh_tokens(AGENT_DIR, START, END, session_logs=tmp_path) == 3500 - 850


def test_codex_ignores_other_agents_sessions(tmp_path):
    rollout = tmp_path / "rollout-2.jsonl"
    rollout.write_text("\n".join([
        json.dumps({"type": "session_meta", "payload": {"cwd": "/somewhere/else"}}),
        codex_event(DURING, 5000, 0, 100),
    ]))
    assert codex_fresh_tokens(AGENT_DIR, START, END, session_logs=tmp_path) is None


# ─────────────── OpenCode ───────────────

def make_opencode_db(path, messages):
    connection = sqlite3.connect(path)
    connection.execute("CREATE TABLE message (id TEXT, data TEXT)")
    for i, message in enumerate(messages):
        connection.execute("INSERT INTO message VALUES (?, ?)", (str(i), json.dumps(message)))
    connection.commit()
    connection.close()


def opencode_message(cwd, iso_time, input_t, output, reasoning, cache_read, cache_write):
    created_ms = int(datetime.fromisoformat(iso_time.replace("Z", "+00:00")).timestamp() * 1000)
    return {"path": {"cwd": cwd}, "time": {"created": created_ms},
            "tokens": {"input": input_t, "output": output, "reasoning": reasoning,
                       "cache": {"read": cache_read, "write": cache_write}}}


def test_opencode_counts_only_this_agent_in_the_window(tmp_path):
    db = tmp_path / "opencode.db"
    make_opencode_db(db, [
        opencode_message(AGENT_DIR, DURING, 100, 20, 5, 99999, 10),         # 135 fresh
        opencode_message(AGENT_DIR, BEFORE, 100, 20, 5, 0, 10),             # before: ignored
        opencode_message("/home/me/Thunderdome", DURING, 500, 50, 0, 0, 0),  # the judge: ignored
    ])

    assert opencode_fresh_tokens(AGENT_DIR, START, END, db_path=db) == 100 + 20 + 5 + 10


def test_opencode_without_a_database_is_unknown(tmp_path):
    assert opencode_fresh_tokens(AGENT_DIR, START, END, db_path=tmp_path / "missing.db") is None


# ─────────────── Ranking with tokens ───────────────

def result(name, passed, tokens, lines, disqualified=None):
    return {"gladiator": name, "passed": passed, "fresh_tokens": tokens,
            "lines_changed": lines, "disqualified": disqualified}


def test_tests_beat_tokens():
    # A cheap wrong answer must never beat an expensive right one.
    ranked = rank([result("cheap", 5, 1_000, 10), result("correct", 9, 90_000, 10)])
    assert ranked[0]["gladiator"] == "correct"


def test_fewer_fresh_tokens_wins_a_tie_on_tests():
    ranked = rank([result("hungry", 9, 80_000, 10), result("frugal", 9, 30_000, 99)])
    assert ranked[0]["gladiator"] == "frugal"


def test_unknown_tokens_skip_the_token_rule_for_everyone():
    # 'unknown' has no log; tokens must not decide, so code lines do.
    ranked = rank([result("known", 9, 1_000, 50), result("unknown", 9, None, 20)])
    assert ranked[0]["gladiator"] == "unknown"


def test_disqualified_gladiators_dont_switch_off_the_token_rule():
    ranked = rank([result("frugal", 9, 1_000, 50), result("hungry", 9, 9_000, 20),
                   result("cheater", 0, None, 0, disqualified="edited core/")])
    assert [r["gladiator"] for r in ranked] == ["frugal", "hungry", "cheater"]
