"""Counts the FRESH tokens each gladiator used during a battle, from its own local logs.

"Fresh" = new input + output. Cache reads (context the model already had, re-read cheaply)
are left out: they mostly measure how long a session ran, not how hard the agent worked.

Each company splits text into tokens differently, so cross-company numbers are
approximate. A big gap (2x, 3x) is still meaningful.

Every reader returns None when it can't find logs, so a missing log never
counts against a gladiator (see judge.rank).
"""

import json
import re
import sqlite3
from datetime import datetime
from pathlib import Path

HOME = Path.home()
CLAUDE_PROJECTS = HOME / ".claude" / "projects"
# Switch gives each Codex session a private copy of Codex's home folder.
CODEX_SESSION_LOGS = HOME / ".local" / "state" / "switch" / "sdk-sessions"
OPENCODE_DB = HOME / ".local" / "share" / "opencode" / "opencode.db"

# Which agent program runs each gladiator (matches thunderdome.template.yaml).
GLADIATOR_PROVIDERS = {
    "claude-gladiator": "claude",
    "codex-gladiator": "codex",
    "opencode-gladiator": "opencode",
}


def parse_time(text: str) -> datetime:
    # Logs write UTC as '...Z'; fromisoformat wants '+00:00'.
    return datetime.fromisoformat(text.replace("Z", "+00:00"))


def in_window(moment: datetime, start: datetime, end: datetime) -> bool:
    return start <= moment <= end


# ─────────────────────────────── Claude Code ───────────────────────────────

def claude_fresh_tokens(agent_dir: Path, start: datetime, end: datetime,
                        projects_dir: Path = CLAUDE_PROJECTS) -> int | None:
    """Claude Code keeps one transcript folder per working directory."""
    # Claude Code names the folder after the path, with every non-alphanumeric character as '-'.
    folder = projects_dir / re.sub(r"[^a-zA-Z0-9]", "-", str(agent_dir))
    transcripts = list(folder.glob("*.jsonl"))
    if not transcripts:
        return None

    usage_by_message = {}
    for transcript in transcripts:
        for line in transcript.read_text(errors="ignore").splitlines():
            try:
                entry = json.loads(line)
            except json.JSONDecodeError:
                continue
            message = entry.get("message")
            if not isinstance(message, dict) or "usage" not in message or "timestamp" not in entry:
                continue
            if in_window(parse_time(entry["timestamp"]), start, end):
                # The same reply can be logged several times; keep one per message id.
                usage_by_message[message.get("id")] = message["usage"]

    return sum(u.get("input_tokens", 0) + u.get("cache_creation_input_tokens", 0) + u.get("output_tokens", 0)
               for u in usage_by_message.values())


# ─────────────────────────────── Codex ───────────────────────────────

def codex_fresh(usage: dict) -> int:
    # output_tokens already includes reasoning ("last_usage_includes_reasoning": true).
    return usage["input_tokens"] - usage["cached_input_tokens"] + usage["output_tokens"]


def codex_fresh_tokens(agent_dir: Path, start: datetime, end: datetime,
                       session_logs: Path = CODEX_SESSION_LOGS) -> int | None:
    """Codex writes one 'rollout' log per session, with a RUNNING total of tokens."""
    found_session = False
    total = 0
    for rollout in session_logs.glob("**/rollout-*.jsonl"):
        lines = rollout.read_text(errors="ignore").splitlines()
        if not lines or json.loads(lines[0]).get("payload", {}).get("cwd") != str(agent_dir):
            continue  # a different agent's session
        found_session = True

        # Running total just before the battle, and at the gladiator's last commit.
        before, at_end = 0, 0
        for line in lines:
            event = json.loads(line)
            payload = event.get("payload", {})
            if payload.get("type") != "token_count" or not payload.get("info"):
                continue
            moment = parse_time(event["timestamp"])
            running = codex_fresh(payload["info"]["total_token_usage"])
            if moment < start:
                before = running
            if moment <= end:
                at_end = running
        # end − start can't double-count, even if an event is logged twice.
        total += max(at_end - before, 0)

    return total if found_session else None


# ─────────────────────────────── OpenCode ───────────────────────────────

def opencode_fresh_tokens(agent_dir: Path, start: datetime, end: datetime,
                          db_path: Path = OPENCODE_DB) -> int | None:
    """OpenCode stores every message, with its token counts, in a SQLite database."""
    if not db_path.exists():
        return None
    # mode=ro: read-only, so the judge can never change OpenCode's data.
    connection = sqlite3.connect(f"file:{db_path}?mode=ro", uri=True)
    try:
        rows = connection.execute("SELECT data FROM message").fetchall()
    finally:
        connection.close()

    found_session = False
    total = 0
    for (data,) in rows:
        message = json.loads(data)
        if (message.get("path") or {}).get("cwd") != str(agent_dir):
            continue  # a different agent, e.g. the judge
        found_session = True
        tokens = message.get("tokens")
        created_ms = (message.get("time") or {}).get("created")
        if not tokens or created_ms is None:
            continue
        # OpenCode stores time as milliseconds since 1970; compare in seconds.
        if start.timestamp() <= created_ms / 1000 <= end.timestamp():
            total += (tokens.get("input", 0) + tokens.get("output", 0) + tokens.get("reasoning", 0)
                      + (tokens.get("cache") or {}).get("write", 0))

    return total if found_session else None


READERS = {"claude": claude_fresh_tokens, "codex": codex_fresh_tokens, "opencode": opencode_fresh_tokens}


def fresh_tokens(gladiator: str, agent_dir: Path, start: datetime, end: datetime) -> int | None:
    """Fresh tokens one gladiator used between start and end, or None if unknown."""
    provider = GLADIATOR_PROVIDERS.get(gladiator)
    if provider is None:
        return None
    try:
        return READERS[provider](agent_dir, start, end)
    except (OSError, json.JSONDecodeError, sqlite3.Error, KeyError):
        # A log we can't read is "unknown", never a crash in the middle of scoring.
        return None
