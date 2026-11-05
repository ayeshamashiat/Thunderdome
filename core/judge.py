"""Scores a battle: runs the judge's hidden tests against each gladiator's code.

Results come only from running code, never from an AI's opinion.
Only COMMITTED work on a gladiator's branch counts.
"""

import json
import subprocess
import sys
import tempfile
import xml.etree.ElementTree as ElementTree
from pathlib import Path

from arena import run_git

# A gladiator's tests get this long before they count as failed (e.g. an infinite loop).
TEST_TIMEOUT_SECONDS = 120


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
            sys.executable, "-m", "pytest", str(hidden_tests),
            "-q",
            "-p", "no:cacheprovider",       # don't leave a .pytest_cache in the worktree
            "--rootdir", str(worktree),     # imports resolve to THIS gladiator's code
            f"--junitxml={report}",         # machine-readable results instead of text
        ]
        # Gladiator code runs inside these tests, so it gets a bare environment:
        # none of your API keys or tokens, just enough to find Python and its own code.
        clean_env = {"PYTHONPATH": str(worktree), "PATH": "/usr/bin:/bin"}
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


def score_gladiator(repo_root: Path, battle: dict, gladiator: str, hidden_tests: Path) -> dict:
    info = battle["gladiators"][gladiator]
    files = changed_files(repo_root, battle["base_commit"], info["branch"])
    lines = lines_changed(repo_root, battle["base_commit"], info["branch"])

    result = {
        "gladiator": gladiator,
        "files_changed": files,
        "lines_changed": lines["code"],   # the tiebreaker
        "test_lines": lines["tests"],     # shown, never penalized
        "disqualified": None,
    }

    # Rule from AGENTS.md: core/ runs the arena itself and is off-limits.
    touched_core = [f for f in files if f.startswith("core/")]
    if touched_core:
        result["disqualified"] = f"edited core/: {', '.join(touched_core)}"
    elif not files:
        result["disqualified"] = "no committed changes"

    if result["disqualified"]:
        result.update({"passed": 0, "total": 0, "error": None})
    else:
        result.update(run_hidden_tests(Path(info["worktree"]), hidden_tests))
    return result


def rank(results: list[dict]) -> list[dict]:
    """Most tests passed wins; on a tie, fewer lines changed wins. Disqualified go last."""
    return sorted(results, key=lambda r: (r["disqualified"] is not None, -r["passed"], r["lines_changed"]))


def score_battle(repo_root: Path, battle_id: str) -> dict:
    battle_dir = repo_root / "battles" / battle_id
    battle = json.loads((battle_dir / "battle.json").read_text())
    hidden_tests = battle_dir / "hidden_tests"

    if not any(hidden_tests.glob("test_*.py")):
        raise FileNotFoundError(f"No hidden tests in {hidden_tests}. The judge must write them first.")

    results = [score_gladiator(repo_root, battle, g, hidden_tests) for g in battle["gladiators"]]
    ranked = rank(results)

    winner = ranked[0]
    # No winner if even the best one passed nothing.
    winner_name = winner["gladiator"] if not winner["disqualified"] and winner["passed"] > 0 else None

    scorecard = {"battle_id": battle_id, "task": battle["task"], "winner": winner_name, "ranking": ranked}
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
            note = f" ⚠️ {r['error']}" if r["error"] else ""
            # .get(): results saved before test_lines existed don't have it.
            lines.append(f"{medal} {r['gladiator']}: {r['passed']}/{r['total']} tests, "
                         f"{r['lines_changed']} code lines (+{r.get('test_lines', 0)} test lines){note}")
    lines.append("")
    lines.append(f"🏆 Winner: {scorecard['winner']}" if scorecard["winner"] else "🤷 No winner this time.")
    return "\n".join(lines)
