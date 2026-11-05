"""Scores a battle: runs the judge's hidden tests against each gladiator's code.

Results come only from running code, never from an AI's opinion.
Only COMMITTED work on a gladiator's branch counts.
"""

import hashlib
import json
import os
import subprocess
import sys
import tempfile
import xml.etree.ElementTree as ElementTree
from datetime import datetime, timezone
from pathlib import Path

from arena import battle_repo, run_git
from tokens import fresh_tokens, parse_time

# A gladiator's tests get this long before they count as failed (e.g. an infinite loop).
TEST_TIMEOUT_SECONDS = 120


def fingerprint_tests(hidden_tests: Path) -> str:
    """A SHA-256 fingerprint of every hidden test file: change one character and it changes.

    Files are hashed in sorted order, name + content, so the same tests always give
    the same fingerprint. __pycache__ is skipped: Python rewrites it on every run.
    """
    digest = hashlib.sha256()
    for path in sorted(hidden_tests.rglob("*")):
        if path.is_file() and "__pycache__" not in path.parts:
            digest.update(str(path.relative_to(hidden_tests)).encode())
            digest.update(path.read_bytes())
    return digest.hexdigest()


def seal_battle(repo_root: Path, battle_id: str) -> str:
    """Record the hidden tests' fingerprint BEFORE gladiators start. Can only be done once."""
    battle_dir = repo_root / "battles" / battle_id
    battle_file = battle_dir / "battle.json"
    battle = json.loads(battle_file.read_text())
    hidden_tests = battle_dir / "hidden_tests"

    if battle.get("sealed_fingerprint"):
        # Re-sealing would let a judge edit the tests after seeing the solutions.
        raise ValueError(f"Battle {battle_id} is already sealed. Seals can't be redone.")
    if not any(hidden_tests.glob("test_*.py")):
        raise FileNotFoundError(f"No hidden tests in {hidden_tests} to seal.")

    battle["sealed_fingerprint"] = fingerprint_tests(hidden_tests)
    battle["sealed_at"] = datetime.now(timezone.utc).isoformat()
    battle_file.write_text(json.dumps(battle, indent=2))
    return battle["sealed_fingerprint"]


def check_seal(battle: dict, hidden_tests: Path) -> str:
    """'intact', 'broken' (tests changed after sealing) or 'unsealed'."""
    sealed = battle.get("sealed_fingerprint")
    if not sealed:
        return "unsealed"
    return "intact" if fingerprint_tests(hidden_tests) == sealed else "broken"


def changed_files(repo_root: Path, base_commit: str, branch: str) -> list[str]:
    """Files the gladiator changed in its commits, compared to where the battle started."""
    output = run_git(repo_root, "diff", "--name-only", base_commit, branch)
    return output.splitlines() if output else []


def is_test_file(path: str) -> bool:
    """Same conventions pytest uses to find tests: a tests/ folder or a test_*.py file."""
    parts = Path(path).parts
    return "tests" in parts[:-1] or parts[-1].startswith("test_")


def lines_changed(repo_root: Path, base_commit: str, branch: str) -> dict:
    """Lines added + removed, split into code and tests.

    Only code lines break ties. Counting test lines too would punish gladiators
    for writing tests, which AGENTS.md tells them to do.
    --numstat prints 'added<TAB>removed<TAB>file' per file.
    """
    counts = {"code": 0, "tests": 0}
    for line in run_git(repo_root, "diff", "--numstat", base_commit, branch).splitlines():
        added, removed, path = line.split("\t", 2)
        # Binary files show '-' instead of numbers; they don't count as lines.
        if added == "-":
            continue
        kind = "tests" if is_test_file(path) else "code"
        counts[kind] += int(added) + int(removed)
    return counts


def run_hidden_tests(worktree: Path, hidden_tests: Path) -> dict:
    """Run the hidden tests against one worktree and count passes and failures."""
    with tempfile.TemporaryDirectory() as tmp:
        report = Path(tmp) / "report.xml"
        command = [
            # -I (isolated mode): Python ignores PYTHONPATH and won't auto-run a
            # sitecustomize.py from the gladiator's folder at startup. Red-teaming showed
            # that trick could rewrite every test result to "passed".
            sys.executable, "-I", "-m", "pytest", str(hidden_tests),
            "-q",
            "-p", "no:cacheprovider",       # don't leave a .pytest_cache in the worktree
            "--rootdir", str(worktree),
            # Added to sys.path by pytest AFTER startup, so imports resolve to THIS
            # gladiator's code without giving it a way to run code at startup.
            "-o", f"pythonpath={worktree}",
            f"--junitxml={report}",         # machine-readable results instead of text
        ]
        # Gladiator code runs inside these tests, so it gets a bare environment:
        # none of your API keys or tokens. PATH is kept (it holds no secrets) so tests
        # for non-Python repos can still run tools like node or npm.
        clean_env = {"PATH": os.environ.get("PATH", "/usr/bin:/bin")}
        try:
            subprocess.run(command, cwd=worktree, capture_output=True, text=True,
                           timeout=TEST_TIMEOUT_SECONDS, env=clean_env)
        except subprocess.TimeoutExpired:
            return {"passed": 0, "total": 0, "error": "tests timed out"}

        if not report.exists():
            return {"passed": 0, "total": 0, "error": "pytest crashed before writing a report"}
        return read_junit_report(report)


def read_junit_report(report: Path) -> dict:
    """Pull the numbers out of pytest's JUnit XML report."""
    suite = ElementTree.parse(report).getroot()
    # Newer pytest wraps everything in <testsuites>; the counts live on <testsuite>.
    if suite.tag == "testsuites":
        suite = suite[0]
    total = int(suite.get("tests", 0))
    not_passed = sum(int(suite.get(key, 0)) for key in ("failures", "errors", "skipped"))
    return {"passed": total - not_passed, "total": total, "error": None}


# Files Python runs automatically, without being imported by anyone.
AUTO_RUN_FILES = ("sitecustomize.py", "usercustomize.py")


def tampering(repo: Path, branch: str, files: list[str]) -> str | None:
    """Spot attempts to fool the test runner. Returns a reason, or None if clean.

    A solution has no business touching pytest's internals; test files may use pytest.
    This can't catch every trick (gladiator code runs in the test process), so it's one
    layer of defense, alongside isolated mode and the honor code.
    """
    for path in files:
        name = Path(path).name
        if name in AUTO_RUN_FILES or name.endswith(".pth"):
            return f"added {path}, a file Python runs automatically"
        if path.endswith(".py") and not is_test_file(path):
            try:
                source = run_git(repo, "show", f"{branch}:{path}")
            except subprocess.CalledProcessError:
                continue  # deleted in the branch: nothing to read
            if "_pytest" in source:
                return f"{path} reaches into pytest's internals"
    return None


def score_gladiator(repo_root: Path, battle: dict, gladiator: str, hidden_tests: Path) -> dict:
    info = battle["gladiators"][gladiator]
    # Branches live in the battle's repo, which may not be Thunderdome (--repo).
    repo = battle_repo(repo_root, battle)
    files = changed_files(repo, battle["base_commit"], info["branch"])
    lines = lines_changed(repo, battle["base_commit"], info["branch"])

    result = {
        "gladiator": gladiator,
        "files_changed": files,
        "lines_changed": lines["code"],   # the tiebreaker
        "test_lines": lines["tests"],     # shown, never penalized
        "disqualified": None,
    }

    # Protected paths are off-limits: core/ in Thunderdome (it runs the arena),
    # or whatever --protect listed for another repo. Old battles predate the field.
    protected = battle.get("protected", ["core/"])
    touched = [f for f in files if any(f.startswith(path) for path in protected)]
    tampered = tampering(repo, info["branch"], files)
    if touched:
        result["disqualified"] = f"edited protected path: {', '.join(touched)}"
    elif tampered:
        result["disqualified"] = f"tampering: {tampered}"
    elif not files:
        result["disqualified"] = "no committed changes"

    if result["disqualified"]:
        result.update({"passed": 0, "total": 0, "error": None})
    else:
        result.update(run_hidden_tests(Path(info["worktree"]), hidden_tests))

    result["fresh_tokens"], result["warning"] = battle_tokens(repo_root, battle, gladiator) if files else (None, None)
    return result


def battle_tokens(repo_root: Path, battle: dict, gladiator: str) -> tuple[int | None, str | None]:
    """Fresh tokens from the battle's start to the gladiator's last commit (when its work was done).

    Returns (tokens, warning). A commit's time is written by whoever commits, so it can be
    faked. A time before the battle (or in the future) would shrink the token window, so
    then we count every token up to now instead: faking the time can only hurt.
    """
    start = parse_time(battle["created_at"])
    now = datetime.now(timezone.utc)
    branch = battle["gladiators"][gladiator]["branch"]
    end = parse_time(run_git(battle_repo(repo_root, battle), "log", "-1", "--format=%cI", branch))
    warning = None
    if not start <= end <= now:
        warning = "commit time is outside the battle; counted all tokens until scoring"
        end = now
    # The Switch directory is the gladiator's arena folder, not the battle worktree inside it.
    return fresh_tokens(gladiator, repo_root / "arena" / gladiator, start, end), warning


def rank(results: list[dict]) -> list[dict]:
    """Most tests passed → fewest fresh tokens → fewest code lines. Disqualified go last.

    Tokens only count if EVERY remaining gladiator has a number: a missing log
    must never help or hurt anyone, so then the token rule is skipped.
    """
    return sorted(results, key=ranking_key(results))


def ranking_key(results: list[dict]):
    """The sort key used by rank(). Two equal keys mean a genuine tie."""
    contenders = [r for r in results if r["disqualified"] is None]
    use_tokens = bool(contenders) and all(r.get("fresh_tokens") is not None for r in contenders)

    def sort_key(r):
        tokens = r["fresh_tokens"] if use_tokens and r["disqualified"] is None else 0
        return (r["disqualified"] is not None, -r["passed"], tokens, r["lines_changed"])

    return sort_key


def tied_for_first(ranked: list[dict]) -> list[str]:
    """Names of everyone sharing first place, when more than one does.

    Without this, a perfect tie would go to whoever happens to be listed first
    (claude-gladiator), which is favoritism by accident.
    """
    key = ranking_key(ranked)
    top = [r for r in ranked if key(r) == key(ranked[0])]
    return [r["gladiator"] for r in top] if len(top) > 1 else []


def score_battle(repo_root: Path, battle_id: str) -> dict:
    battle_dir = repo_root / "battles" / battle_id
    battle = json.loads((battle_dir / "battle.json").read_text())
    hidden_tests = battle_dir / "hidden_tests"

    if battle.get("mode") == "blind":
        raise ValueError(f"Battle {battle_id} is a blind battle: use 'ballot' and then 'vote', not 'score'.")
    if not any(hidden_tests.glob("test_*.py")):
        raise FileNotFoundError(f"No hidden tests in {hidden_tests}. The judge must write them first.")

    results = [score_gladiator(repo_root, battle, g, hidden_tests) for g in battle["gladiators"]]
    ranked = rank(results)

    winner = ranked[0]
    # No winner if even the best one passed nothing.
    has_winner = not winner["disqualified"] and winner["passed"] > 0
    draw = tied_for_first(ranked) if has_winner else []
    winner_name = winner["gladiator"] if has_winner and not draw else None

    scorecard = {
        "battle_id": battle_id,
        "task": battle["task"],
        "winner": winner_name,
        "draw": draw,
        "seal": check_seal(battle, hidden_tests),
        "sealed_fingerprint": battle.get("sealed_fingerprint"),
        "ranking": ranked,
    }
    (battle_dir / "results.json").write_text(json.dumps(scorecard, indent=2))
    return scorecard


def format_scorecard(scorecard: dict) -> str:
    """A short text scorecard the judge agent can paste into the room."""
    medals = ["🥇", "🥈", "🥉"]
    lines = [f"⚖️ Battle {scorecard['battle_id']}: {scorecard['task']}", ""]
    for place, r in enumerate(scorecard["ranking"]):
        medal = medals[place] if place < len(medals) else "  "
        if r["disqualified"]:
            lines.append(f"🚫 {r['gladiator']}: DISQUALIFIED ({r['disqualified']})")
        else:
            problems = [text for text in (r["error"], r.get("warning")) if text]
            note = "".join(f" ⚠️ {text}" for text in problems)
            # .get(): results saved before these fields existed don't have them.
            tokens = r.get("fresh_tokens")
            token_text = f"{tokens / 1000:.1f}k fresh tokens" if tokens is not None else "tokens n/a"
            lines.append(f"{medal} {r['gladiator']}: {r['passed']}/{r['total']} tests, {token_text}, "
                         f"{r['lines_changed']} code lines (+{r.get('test_lines', 0)} test lines){note}")
    lines.append("")
    if scorecard["winner"]:
        lines.append(f"🏆 Winner: {scorecard['winner']}")
    elif scorecard.get("draw"):
        lines.append(f"🤝 DRAW between {' and '.join(scorecard['draw'])}. "
                     f"The owner picks: arena.py merge {scorecard['battle_id']} --pick <gladiator>")
    else:
        lines.append("🤷 No winner this time.")

    # .get(): scorecards saved before sealing existed have no "seal" key.
    seal = scorecard.get("seal", "unsealed")
    if seal == "intact":
        lines.append(f"🔒 Hidden tests sealed before the battle and unchanged ({scorecard['sealed_fingerprint'][:12]})")
    elif seal == "broken":
        lines.append("🚨 HIDDEN TESTS WERE CHANGED AFTER SEALING. Don't trust this result.")
    else:
        lines.append("⚠️ Hidden tests were never sealed for this battle.")
    return "\n".join(lines)
