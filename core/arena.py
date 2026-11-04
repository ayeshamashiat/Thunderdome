"""Thunderdome arena engine: sets up and cleans up battles between gladiators.

Usage:
    python core/arena.py setup <name> "<task description>"
    python core/arena.py cleanup <battle-id>

Each gladiator gets its own git worktree (a separate folder on its own branch),
so no gladiator can see or overwrite another's work.
"""

import argparse
import json
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path

# The repo root is the folder above core/, wherever the project is cloned.
REPO_ROOT = Path(__file__).resolve().parent.parent

GLADIATORS = ["claude-gladiator", "codex-gladiator", "opencode-gladiator"]

# Battles always start from this branch, so every gladiator gets the same code.
BASE_BRANCH = "main"


def run_git(repo_root: Path, *args: str) -> str:
    """Run a git command in repo_root and return its output.

    check=True makes Python raise an error if git fails, instead of
    silently carrying on with a half-made battle.
    """
    result = subprocess.run(
        ["git", *args],
        cwd=repo_root,
        capture_output=True,
        text=True,
        check=True,
    )
    return result.stdout.strip()


def next_battle_id(battles_dir: Path, name: str) -> str:
    """Make a numbered ID like '003-leaderboard' so battles sort in order."""
    existing = [p for p in battles_dir.iterdir() if p.is_dir()] if battles_dir.exists() else []
    return f"{len(existing) + 1:03d}-{name}"


def branch_name(battle_id: str, gladiator: str) -> str:
    return f"battle/{battle_id}/{gladiator}"


def worktree_path(repo_root: Path, battle_id: str, gladiator: str) -> Path:
    # The worktree goes INSIDE the gladiator's own folder (its Switch directory),
    # because agents like Codex may only edit files inside their working folder.
    return repo_root / "arena" / gladiator / battle_id


def setup_battle(repo_root: Path, name: str, task: str, gladiators=GLADIATORS) -> dict:
    """Create one worktree + branch per gladiator and the judge's battle folder."""
    battles_dir = repo_root / "battles"
    battle_id = next_battle_id(battles_dir, name)

    # Gladiators only see COMMITTED code, so uncommitted changes would be missing.
    if run_git(repo_root, "status", "--porcelain", "--untracked-files=no"):
        print(f"⚠️  You have uncommitted changes. Gladiators will only see what's committed on '{BASE_BRANCH}'.")

    base_commit = run_git(repo_root, "rev-parse", BASE_BRANCH)

    battle = {
        "id": battle_id,
        "task": task,
        "created_at": datetime.now(timezone.utc).isoformat(),
        "base_commit": base_commit,
        "gladiators": {},
    }

    for gladiator in gladiators:
        branch = branch_name(battle_id, gladiator)
        path = worktree_path(repo_root, battle_id, gladiator)
        # -b creates a new branch for this gladiator, starting from base_commit.
        run_git(repo_root, "worktree", "add", "-b", branch, str(path), base_commit)
        battle["gladiators"][gladiator] = {"branch": branch, "worktree": str(path)}

    # The judge's private folder. battles/ is gitignored, so it never appears
    # inside a worktree: that's what keeps the hidden tests hidden.
    battle_dir = battles_dir / battle_id
    (battle_dir / "hidden_tests").mkdir(parents=True)
    (battle_dir / "battle.json").write_text(json.dumps(battle, indent=2))

    return battle


def cleanup_battle(repo_root: Path, battle_id: str) -> None:
    """Remove a battle's worktrees and branches. The battle record is kept as history."""
    battle_file = repo_root / "battles" / battle_id / "battle.json"
    battle = json.loads(battle_file.read_text())

    for gladiator, info in battle["gladiators"].items():
        # --force: a gladiator may have left uncommitted files behind.
        run_git(repo_root, "worktree", "remove", "--force", info["worktree"])
        # -D deletes the branch even if it was never merged (losers' branches).
        run_git(repo_root, "branch", "-D", info["branch"])
        print(f"🧹 removed {gladiator}'s worktree and branch")


def main() -> None:
    parser = argparse.ArgumentParser(description="Thunderdome arena engine")
    commands = parser.add_subparsers(dest="command", required=True)

    setup_cmd = commands.add_parser("setup", help="start a new battle")
    setup_cmd.add_argument("name", help="short battle name, e.g. leaderboard")
    setup_cmd.add_argument("task", help="what the gladiators must build")

    cleanup_cmd = commands.add_parser("cleanup", help="remove a battle's worktrees")
    cleanup_cmd.add_argument("battle_id", help="e.g. 001-leaderboard")

    args = parser.parse_args()

    try:
        if args.command == "setup":
            battle = setup_battle(REPO_ROOT, args.name, args.task)
            print(f"⚔️  Battle {battle['id']} is ready!")
            for gladiator, info in battle["gladiators"].items():
                print(f"   {gladiator}: {info['worktree']}")
        elif args.command == "cleanup":
            cleanup_battle(REPO_ROOT, args.battle_id)
    except subprocess.CalledProcessError as error:
        # Show git's own error message, which is usually the most helpful part.
        print(f"❌ git failed: {error.stderr.strip()}", file=sys.stderr)
        sys.exit(1)


if __name__ == "__main__":
    main()
