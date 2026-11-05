"""Thunderdome arena engine: sets up and cleans up battles between gladiators.

Usage:
    python core/arena.py init                              # once, after cloning
    python core/arena.py setup <name> "<task description>"
    python core/arena.py setup <name> "<task>" --repo /path/to/project [--protect src/config/]
    python core/arena.py seal <battle-id>                  # after writing hidden tests, before announcing
    python core/arena.py score <battle-id>
    python core/arena.py merge <battle-id>                 # only after the user says merge
    python core/arena.py cleanup <battle-id>

Each gladiator gets its own git worktree (a separate folder on its own branch),
so no gladiator can see or overwrite another's work.

A battle can happen in Thunderdome itself or in any other git repo (--repo).
The judge's files (hidden tests, results) always stay in Thunderdome's battles/.
"""

import argparse
import json
import re
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path

# The repo root is the folder above core/, wherever the project is cloned.
REPO_ROOT = Path(__file__).resolve().parent.parent

GLADIATORS = ["claude-gladiator", "codex-gladiator", "opencode-gladiator"]

# Battles in Thunderdome itself start from this branch. Battles in other repos
# start from whatever branch that repo is on (it may be master, dev, ...).
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


# Lowercase letters, digits and dashes: safe in folder names AND git branch names.
BATTLE_NAME = re.compile(r"[a-z0-9][a-z0-9-]{0,40}")


def check_battle_name(name: str) -> None:
    if not BATTLE_NAME.fullmatch(name):
        raise ValueError(f"Battle name {name!r} must be lowercase letters, digits and dashes, "
                         "e.g. 'leaderboard' or 'fix-login'.")


def next_battle_id(battles_dir: Path, name: str) -> str:
    """Make a numbered ID like '003-leaderboard' so battles sort in order.

    Uses the highest number so far + 1 (not a count), so deleting an old
    battle folder can never make two battles share a number.
    """
    numbers = [int(p.name.split("-", 1)[0]) for p in battles_dir.glob("*")
               if p.is_dir() and p.name.split("-", 1)[0].isdigit()] if battles_dir.exists() else []
    return f"{max(numbers, default=0) + 1:03d}-{name}"


def branch_name(battle_id: str, gladiator: str) -> str:
    return f"battle/{battle_id}/{gladiator}"


def worktree_path(repo_root: Path, battle_id: str, gladiator: str) -> Path:
    # The worktree goes INSIDE the gladiator's own folder (its Switch directory),
    # because agents like Codex may only edit files inside their working folder.
    return repo_root / "arena" / gladiator / battle_id


def load_battle(repo_root: Path, battle_id: str) -> dict:
    return json.loads((repo_root / "battles" / battle_id / "battle.json").read_text())


def battle_repo(repo_root: Path, battle: dict) -> Path:
    """The repo a battle happens in. Battles from before --repo existed were all in Thunderdome."""
    return Path(battle.get("repo", repo_root))


def battle_base_branch(battle: dict) -> str:
    return battle.get("base_branch", BASE_BRANCH)


def resolve_target_repo(target_repo) -> tuple[Path, str]:
    """Check the target is a git repo on a branch. Returns (repo top folder, current branch)."""
    target = Path(target_repo).expanduser().resolve()
    if not target.is_dir():
        raise ValueError(f"{target} is not a folder.")
    try:
        # A subfolder of a repo is fine: always work from the repo's top folder.
        target = Path(run_git(target, "rev-parse", "--show-toplevel"))
    except subprocess.CalledProcessError:
        raise ValueError(f"{target} is not a git repository.")
    branch = run_git(target, "branch", "--show-current")
    if not branch:
        raise ValueError(f"{target} isn't on a branch (detached HEAD). Check out a branch first.")
    return target, branch


def setup_battle(repo_root: Path, name: str, task: str, gladiators=GLADIATORS,
                 target_repo=None, protected=None) -> dict:
    """Create one worktree + branch per gladiator and the judge's battle folder.

    target_repo: battle in another git repo (default: Thunderdome itself).
    protected:   paths gladiators must not touch (default: core/ in Thunderdome, nothing elsewhere).
    """
    check_battle_name(name)
    battles_dir = repo_root / "battles"
    battle_id = next_battle_id(battles_dir, name)

    if target_repo is None:
        target, base_branch = repo_root, BASE_BRANCH
    else:
        target, base_branch = resolve_target_repo(target_repo)

    is_thunderdome = target.resolve() == repo_root.resolve()
    if protected is None:
        protected = ["core/"] if is_thunderdome else []

    # Gladiators only see COMMITTED code, so uncommitted changes would be missing.
    if run_git(target, "status", "--porcelain", "--untracked-files=no"):
        print(f"⚠️  {target} has uncommitted changes. Gladiators only see what's committed on '{base_branch}'.")

    base_commit = run_git(target, "rev-parse", base_branch)

    battle = {
        "id": battle_id,
        "task": task,
        "created_at": datetime.now(timezone.utc).isoformat(),
        "repo": str(target),
        "base_branch": base_branch,
        "base_commit": base_commit,
        # Normalise "./src/config" to "src/config", so it matches git's file paths.
        "protected": [p.removeprefix("./") for p in protected],
        "gladiators": {},
    }

    try:
        for gladiator in gladiators:
            branch = branch_name(battle_id, gladiator)
            # Worktrees always live in Thunderdome's arena/, the gladiators' Switch folders,
            # even when the code comes from another repo.
            path = worktree_path(repo_root, battle_id, gladiator)
            # -b creates a new branch for this gladiator, starting from base_commit.
            run_git(target, "worktree", "add", "-b", branch, str(path), base_commit)
            battle["gladiators"][gladiator] = {"branch": branch, "worktree": str(path)}
    except subprocess.CalledProcessError:
        # All or nothing: undo the gladiators already set up, so a retry starts clean.
        for info in battle["gladiators"].values():
            remove_worktree_and_branch(target, info)
        raise

    # The judge's private folder. battles/ is gitignored, so it never appears
    # inside a worktree: that's what keeps the hidden tests hidden.
    battle_dir = battles_dir / battle_id
    (battle_dir / "hidden_tests").mkdir(parents=True)
    (battle_dir / "battle.json").write_text(json.dumps(battle, indent=2))

    return battle


def init_arena(repo_root: Path, gladiators=GLADIATORS) -> list[Path]:
    """Create each gladiator's folder. Switch needs an agent's directory to exist before creating the agent."""
    folders = [repo_root / "arena" / gladiator for gladiator in gladiators]
    for folder in folders + [repo_root / "battles"]:
        folder.mkdir(parents=True, exist_ok=True)
    return folders


def merge_winner(repo_root: Path, battle_id: str, pick: str | None = None) -> str:
    """Merge the winner's branch into the battle's base branch, after tagging a checkpoint to undo to.

    pick: after a DRAW, the owner chooses which tied gladiator to merge.
          Not allowed when there's a clear winner: tests decide, not preferences.
    Returns the checkpoint tag name.
    """
    battle_dir = repo_root / "battles" / battle_id
    battle = load_battle(repo_root, battle_id)
    repo, base_branch = battle_repo(repo_root, battle), battle_base_branch(battle)
    results_file = battle_dir / "results.json"
    if not results_file.exists():
        raise ValueError(f"Battle {battle_id} hasn't been scored yet. Run: arena.py score {battle_id}")
    results = json.loads(results_file.read_text())

    winner = results["winner"]
    draw = results.get("draw") or []
    if pick is not None:
        if pick not in draw:
            raise ValueError(f"--pick only works for a draw, and {pick!r} isn't tied for first.")
        winner = pick
    elif draw:
        raise ValueError(f"Battle {battle_id} is a draw between {' and '.join(draw)}. "
                         f"Choose one: arena.py merge {battle_id} --pick <gladiator>")
    if winner is None:
        raise ValueError(f"Battle {battle_id} has no winner, so there's nothing to merge.")
    if results.get("merged"):
        raise ValueError(f"Battle {battle_id} was already merged.")
    if results.get("seal") == "broken":
        raise ValueError(f"Battle {battle_id}'s hidden tests changed after sealing. Refusing to merge.")

    if run_git(repo, "branch", "--show-current") != base_branch:
        raise ValueError(f"Switch {repo} to '{base_branch}' before merging.")
    # Merging on top of uncommitted changes would mix your work with the winner's.
    if run_git(repo, "status", "--porcelain", "--untracked-files=no"):
        raise ValueError(f"{repo} has uncommitted changes on {base_branch}. Commit or stash them first.")

    # A tag is a permanent bookmark. To undo the merge: git reset --hard <tag>
    checkpoint = f"checkpoint/before-{battle_id}"
    run_git(repo, "tag", checkpoint)

    branch = battle["gladiators"][winner]["branch"]
    try:
        # --no-ff always makes a merge commit, so history shows exactly where a battle landed.
        run_git(repo, "merge", "--no-ff", "-m", f"Battle {battle_id}: merge {winner}'s solution", branch)
    except subprocess.CalledProcessError:
        # A conflict leaves files half-merged; abort so the branch is exactly as it was.
        run_git(repo, "merge", "--abort")
        raise

    results["merged"] = True
    results["merged_gladiator"] = winner
    results_file.write_text(json.dumps(results, indent=2))
    return checkpoint


def remove_worktree_and_branch(repo: Path, info: dict) -> None:
    """Remove one gladiator's worktree and branch. Safe to run twice: missing pieces are skipped."""
    if Path(info["worktree"]).exists():
        # --force: a gladiator may have left uncommitted files behind.
        run_git(repo, "worktree", "remove", "--force", info["worktree"])
    else:
        # The folder is already gone; forget git's record of it.
        run_git(repo, "worktree", "prune")
    if run_git(repo, "branch", "--list", info["branch"]):
        # -D deletes the branch even if it was never merged (losers' branches).
        run_git(repo, "branch", "-D", info["branch"])


def cleanup_battle(repo_root: Path, battle_id: str) -> None:
    """Remove a battle's worktrees and branches. The battle record is kept as history."""
    battle = load_battle(repo_root, battle_id)
    repo = battle_repo(repo_root, battle)

    for gladiator, info in battle["gladiators"].items():
        remove_worktree_and_branch(repo, info)
        print(f"🧹 removed {gladiator}'s worktree and branch")


def main() -> None:
    parser = argparse.ArgumentParser(description="Thunderdome arena engine")
    commands = parser.add_subparsers(dest="command", required=True)

    commands.add_parser("init", help="create the gladiators' folders (run once after cloning)")

    merge_cmd = commands.add_parser("merge", help="merge the winner into main (checkpoint first)")
    merge_cmd.add_argument("battle_id", help="e.g. 001-leaderboard")
    merge_cmd.add_argument("--pick", help="after a draw: which tied gladiator to merge")

    setup_cmd = commands.add_parser("setup", help="start a new battle")
    setup_cmd.add_argument("name", help="short battle name, e.g. leaderboard")
    setup_cmd.add_argument("task", help="what the gladiators must build")
    setup_cmd.add_argument("--repo", help="battle in this git repo instead of Thunderdome")
    setup_cmd.add_argument("--protect", action="append", default=None, metavar="PATH",
                           help="a path gladiators must not edit (repeatable)")

    seal_cmd = commands.add_parser("seal", help="fingerprint the hidden tests before the battle starts")
    seal_cmd.add_argument("battle_id", help="e.g. 001-leaderboard")

    score_cmd = commands.add_parser("score", help="run hidden tests and rank the gladiators")
    score_cmd.add_argument("battle_id", help="e.g. 001-leaderboard")

    cleanup_cmd = commands.add_parser("cleanup", help="remove a battle's worktrees")
    cleanup_cmd.add_argument("battle_id", help="e.g. 001-leaderboard")

    args = parser.parse_args()

    try:
        if args.command == "init":
            for folder in init_arena(REPO_ROOT):
                print(f"📁 {folder}")
            print("✅ Arena ready. Use these folders as the gladiators' Directory in Switch.")
        elif args.command == "merge":
            checkpoint = merge_winner(REPO_ROOT, args.battle_id, pick=args.pick)
            battle = load_battle(REPO_ROOT, args.battle_id)
            repo = battle_repo(REPO_ROOT, battle)
            print(f"🏆 Winner merged into {battle_base_branch(battle)} of {repo}.")
            print(f"↩️  To undo: git -C {repo} reset --hard {checkpoint}")
        elif args.command == "setup":
            battle = setup_battle(REPO_ROOT, args.name, args.task,
                                  target_repo=args.repo, protected=args.protect)
            print(f"⚔️  Battle {battle['id']} is ready in {battle['repo']} (from '{battle['base_branch']}').")
            if battle["protected"]:
                print(f"   🔒 Protected: {', '.join(battle['protected'])}")
            for gladiator, info in battle["gladiators"].items():
                print(f"   {gladiator}: {info['worktree']}")
        elif args.command == "seal":
            from judge import seal_battle  # see the note on circular imports below
            fingerprint = seal_battle(REPO_ROOT, args.battle_id)
            print(f"🔒 Hidden tests sealed. Fingerprint: {fingerprint}")
            print("   Post this in the room. Any change to the tests will show up when scoring.")
        elif args.command == "score":
            # Imported here, not at the top: judge.py imports arena.py,
            # so importing it at the top would make the two files import each other.
            from judge import format_scorecard, score_battle
            print(format_scorecard(score_battle(REPO_ROOT, args.battle_id)))
        elif args.command == "cleanup":
            cleanup_battle(REPO_ROOT, args.battle_id)
    except subprocess.CalledProcessError as error:
        # Show git's own error message, which is usually the most helpful part.
        print(f"❌ git failed: {error.stderr.strip()}", file=sys.stderr)
        sys.exit(1)
    except (FileNotFoundError, ValueError) as error:
        print(f"❌ {error}", file=sys.stderr)
        sys.exit(1)


if __name__ == "__main__":
    main()
