"""Blind-vote battles: for writing and creative tasks, where no test can say who's best.

The owner reads the entries as A, B, C (random order, names hidden), votes,
and only then learns which AI wrote which. Like a blind taste test.
"""

import json
import re
import secrets
import subprocess
from pathlib import Path

from arena import battle_repo, load_battle, run_git
from judge import battle_tokens, changed_files

# Words that would give away who wrote an entry. Matched case-insensitively, as whole words.
IDENTITY_WORDS = [
    "claude", "anthropic", "codex", "openai", "chatgpt", "gpt", "opencode",
    "deepseek", "gemini", "google", "glm", "zhipu", "gladiator",
]
IDENTITY_PATTERN = re.compile(r"\b(" + "|".join(IDENTITY_WORDS) + r")[\w-]*", re.IGNORECASE)


def scrub_identity(text: str) -> tuple[str, list[str]]:
    """Replace names that reveal the author. Returns (clean text, words that were removed)."""
    found = sorted({match.group(0) for match in IDENTITY_PATTERN.finditer(text)})
    return IDENTITY_PATTERN.sub("[redacted]", text), found


def read_deliverable(repo: Path, branch: str, path: str) -> str | None:
    """The deliverable as COMMITTED on the gladiator's branch, or None if it isn't there."""
    try:
        return run_git(repo, "show", f"{branch}:{path}")
    except subprocess.CalledProcessError:
        return None


def make_ballot(repo_root: Path, battle_id: str) -> dict:
    """Shuffle the committed entries into letters A, B, C… and save the ballot.

    The letter → gladiator mapping stays in the judge's private battles/ folder.
    """
    battle = load_battle(repo_root, battle_id)
    if battle.get("mode") != "blind":
        raise ValueError(f"Battle {battle_id} isn't a blind battle. Use: arena.py score {battle_id}")
    battle_dir = repo_root / "battles" / battle_id
    if (battle_dir / "ballot.json").exists():
        # A second shuffle would let someone re-roll the letters after peeking.
        raise ValueError(f"Battle {battle_id} already has a ballot.")

    repo = battle_repo(repo_root, battle)
    entries, disqualified = [], {}
    for gladiator, info in battle["gladiators"].items():
        if not changed_files(repo, battle["base_commit"], info["branch"]):
            disqualified[gladiator] = "no committed changes"
            continue
        text = read_deliverable(repo, info["branch"], battle["deliverable"])
        if text is None:
            disqualified[gladiator] = f"no {battle['deliverable']} committed"
            continue
        clean, signed = scrub_identity(text)
        entries.append({"gladiator": gladiator, "text": clean, "signed_with": signed})

    if not entries:
        raise ValueError(f"Nobody committed {battle['deliverable']}, so there's nothing to vote on.")

    # secrets: unpredictable order, so nobody can guess which letter is which AI.
    secrets.SystemRandom().shuffle(entries)
    letters = [chr(ord("A") + i) for i in range(len(entries))]
    ballot = {
        "battle_id": battle_id,
        "task": battle["task"],
        "entries": {letter: entry for letter, entry in zip(letters, entries)},
        "disqualified": disqualified,
        "voted": None,
    }
    (battle_dir / "ballot.json").write_text(json.dumps(ballot, indent=2))
    return ballot


def format_ballot(ballot: dict) -> str:
    """What the room sees: the entries by letter only. No names, no hints."""
    lines = [f"🙈 Blind vote: battle {ballot['battle_id']}: {ballot['task']}",
             "Read them all, then vote with: @arena-judge vote <letter>", ""]
    for letter, entry in ballot["entries"].items():
        lines += [f"━━━━━━━━━━ Entry {letter} ━━━━━━━━━━", entry["text"].strip(), ""]
    return "\n".join(lines)


def cast_vote(repo_root: Path, battle_id: str, letter: str) -> dict:
    """Record the owner's vote, reveal who wrote what, and save results.json (so merge works)."""
    battle_dir = repo_root / "battles" / battle_id
    ballot_file = battle_dir / "ballot.json"
    if not ballot_file.exists():
        raise ValueError(f"No ballot yet. Run: arena.py ballot {battle_id}")
    ballot = json.loads(ballot_file.read_text())
    if ballot["voted"]:
        raise ValueError(f"Battle {battle_id} was already decided (vote: {ballot['voted']}).")

    letter = letter.strip().upper()
    if letter not in ballot["entries"]:
        raise ValueError(f"Pick one of: {', '.join(ballot['entries'])}")

    battle = load_battle(repo_root, battle_id)
    winner = ballot["entries"][letter]["gladiator"]
    ranking = []
    for entry_letter, entry in ballot["entries"].items():
        tokens, _ = battle_tokens(repo_root, battle, entry["gladiator"])
        ranking.append({
            "gladiator": entry["gladiator"],
            "letter": entry_letter,
            "votes": 1 if entry_letter == letter else 0,
            "fresh_tokens": tokens,
            "signed_with": entry["signed_with"],
            "disqualified": None,
        })
    ranking.sort(key=lambda r: -r["votes"])
    ranking += [{"gladiator": g, "letter": None, "votes": 0, "fresh_tokens": None,
                 "signed_with": [], "disqualified": reason}
                for g, reason in ballot["disqualified"].items()]

    ballot["voted"] = letter
    ballot_file.write_text(json.dumps(ballot, indent=2))

    results = {
        "battle_id": battle_id,
        "task": battle["task"],
        "mode": "blind",
        "winner": winner,
        "draw": [],
        "vote": letter,
        "seal": "not used in blind battles",
        "ranking": ranking,
    }
    (battle_dir / "results.json").write_text(json.dumps(results, indent=2))
    return results


def format_reveal(results: dict) -> str:
    lines = [f"🎭 THE REVEAL: battle {results['battle_id']}: {results['task']}", ""]
    for r in results["ranking"]:
        if r["disqualified"]:
            lines.append(f"🚫 {r['gladiator']}: DISQUALIFIED ({r['disqualified']})")
            continue
        crown = "🏆" if r["votes"] else "  "
        tokens = f"{r['fresh_tokens'] / 1000:.1f}k fresh tokens" if r["fresh_tokens"] is not None else "tokens n/a"
        signed = f" ✍️ tried to sign it ({', '.join(r['signed_with'])}), redacted" if r["signed_with"] else ""
        lines.append(f"{crown} Entry {r['letter']} was… {r['gladiator']} ({tokens}){signed}")
    lines += ["", f"You picked {results['vote']}. Winner: {results['winner']}"]
    return "\n".join(lines)
