"""Tests for the judge. Each test stages a tiny fake battle in a throwaway repo."""

import json

import pytest

from arena import init_arena, merge_winner, run_git, setup_battle
from judge import format_scorecard, rank, score_battle, seal_battle

HIDDEN_TEST = """
from extras.greet import greet

def test_greets_by_name():
    assert greet("Ada") == "Hello, Ada!"

def test_greets_world_by_default():
    assert greet() == "Hello, world!"
"""


@pytest.fixture
def repo(tmp_path):
    run_git(tmp_path, "init", "-b", "main", "-q")
    run_git(tmp_path, "config", "user.email", "test@example.com")
    run_git(tmp_path, "config", "user.name", "Test")
    (tmp_path / ".gitignore").write_text("arena/\nbattles/\n")
    (tmp_path / "core").mkdir()
    (tmp_path / "core" / "engine.py").write_text("# arena engine\n")
    (tmp_path / "extras").mkdir()
    (tmp_path / "extras" / "README.md").write_text("extras\n")
    run_git(tmp_path, "add", ".")
    run_git(tmp_path, "commit", "-q", "-m", "first")
    return tmp_path


def gladiator_commits(repo, gladiator, files: dict[str, str]):
    """Pretend to be a gladiator: write files in its worktree and commit them."""
    worktree = repo / "arena" / gladiator / "001-greet"
    for relative_path, content in files.items():
        path = worktree / relative_path
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(content)
    run_git(worktree, "add", ".")
    run_git(worktree, "commit", "-q", "-m", f"{gladiator}'s solution")


def start_battle(repo, gladiators):
    setup_battle(repo, "greet", "write greet()", gladiators)
    (repo / "battles" / "001-greet" / "hidden_tests" / "test_greet.py").write_text(HIDDEN_TEST)


def test_correct_solution_beats_buggy_one(repo):
    start_battle(repo, ["good", "buggy"])
    gladiator_commits(repo, "good", {"extras/greet.py":
        'def greet(name="world"):\n    return f"Hello, {name}!"\n'})
    gladiator_commits(repo, "buggy", {"extras/greet.py":
        'def greet(name):\n    return f"Hi {name}"\n'})

    scorecard = score_battle(repo, "001-greet")

    assert scorecard["winner"] == "good"
    good, buggy = scorecard["ranking"]
    assert (good["passed"], good["total"]) == (2, 2)
    assert buggy["passed"] == 0


def test_editing_core_is_disqualified(repo):
    start_battle(repo, ["cheater", "honest"])
    gladiator_commits(repo, "cheater", {
        "extras/greet.py": 'def greet(name="world"):\n    return f"Hello, {name}!"\n',
        "core/engine.py": "# I rewrote the arena\n",
    })
    gladiator_commits(repo, "honest", {"extras/greet.py":
        'def greet(name="world"):\n    return f"Hello, {name}!"\n'})

    scorecard = score_battle(repo, "001-greet")

    assert scorecard["winner"] == "honest"
    cheater = scorecard["ranking"][-1]
    assert "core/engine.py" in cheater["disqualified"]


def test_uncommitted_work_does_not_count(repo):
    start_battle(repo, ["lazy"])
    worktree = repo / "arena" / "lazy" / "001-greet"
    (worktree / "extras" / "greet.py").write_text('def greet(name="world"):\n    return f"Hello, {name}!"\n')

    scorecard = score_battle(repo, "001-greet")

    assert scorecard["winner"] is None
    assert scorecard["ranking"][0]["disqualified"] == "no committed changes"


def test_results_are_saved_for_extras_to_read(repo):
    start_battle(repo, ["good"])
    gladiator_commits(repo, "good", {"extras/greet.py":
        'def greet(name="world"):\n    return f"Hello, {name}!"\n'})

    score_battle(repo, "001-greet")

    saved = json.loads((repo / "battles" / "001-greet" / "results.json").read_text())
    assert saved["winner"] == "good"


def test_scoring_without_hidden_tests_fails_clearly(repo):
    setup_battle(repo, "greet", "write greet()", ["good"])
    with pytest.raises(FileNotFoundError, match="hidden tests"):
        score_battle(repo, "001-greet")


def test_tie_goes_to_the_smaller_solution():
    results = [
        {"gladiator": "verbose", "passed": 2, "lines_changed": 90, "disqualified": None},
        {"gladiator": "tidy", "passed": 2, "lines_changed": 12, "disqualified": None},
    ]
    assert [r["gladiator"] for r in rank(results)] == ["tidy", "verbose"]


def test_scorecard_text_names_the_winner():
    scorecard = {"battle_id": "001-greet", "task": "write greet()", "winner": "tidy", "ranking": [
        {"gladiator": "tidy", "passed": 2, "total": 2, "lines_changed": 12, "disqualified": None, "error": None},
    ]}
    text = format_scorecard(scorecard)
    assert "🥇 tidy: 2/2 tests" in text
    assert "🏆 Winner: tidy" in text


# --- After the battle: merging the winner ---

GOOD_GREET = 'def greet(name="world"):\n    return f"Hello, {name}!"\n'


def scored_battle(repo):
    """A finished, scored battle that 'good' won."""
    start_battle(repo, ["good", "buggy"])
    gladiator_commits(repo, "good", {"extras/greet.py": GOOD_GREET})
    gladiator_commits(repo, "buggy", {"extras/greet.py": "def greet(name):\n    return name\n"})
    score_battle(repo, "001-greet")


def test_merge_brings_the_winners_code_into_main(repo):
    scored_battle(repo)

    checkpoint = merge_winner(repo, "001-greet")

    assert (repo / "extras" / "greet.py").read_text() == GOOD_GREET
    assert "merge good's solution" in run_git(repo, "log", "-1", "--format=%s")
    # The checkpoint points at main as it was before the merge, so it can be undone.
    assert run_git(repo, "rev-parse", checkpoint) == run_git(repo, "rev-parse", "HEAD^1")


def test_merge_refuses_when_main_has_uncommitted_changes(repo):
    scored_battle(repo)
    (repo / "core" / "engine.py").write_text("# half-finished edit\n")

    with pytest.raises(ValueError, match="uncommitted"):
        merge_winner(repo, "001-greet")


def test_merge_refuses_without_a_winner(repo):
    start_battle(repo, ["lazy"])
    score_battle(repo, "001-greet")

    with pytest.raises(ValueError, match="no winner"):
        merge_winner(repo, "001-greet")


def test_merge_refuses_before_scoring(repo):
    start_battle(repo, ["good"])

    with pytest.raises(ValueError, match="hasn't been scored"):
        merge_winner(repo, "001-greet")


def test_init_creates_a_folder_per_gladiator(tmp_path):
    folders = init_arena(tmp_path, ["alpha", "beta"])

    assert [f.name for f in folders] == ["alpha", "beta"]
    assert all(f.is_dir() for f in folders)
    assert (tmp_path / "battles").is_dir()


# --- Tiebreaker fairness ---

def test_writing_tests_does_not_cost_you_the_tiebreak(repo):
    start_battle(repo, ["no_tests", "tested"])
    gladiator_commits(repo, "no_tests", {"extras/greet.py": GOOD_GREET})
    gladiator_commits(repo, "tested", {
        "extras/greet.py": GOOD_GREET,
        "extras/tests/test_greet.py": "from extras.greet import greet\n\ndef test_it():\n    assert greet()\n",
    })

    scorecard = score_battle(repo, "001-greet")

    by_name = {r["gladiator"]: r for r in scorecard["ranking"]}
    assert by_name["tested"]["lines_changed"] == by_name["no_tests"]["lines_changed"]
    assert by_name["tested"]["test_lines"] == 4


# --- Sealing the hidden tests ---

def hidden_test_file(repo):
    return repo / "battles" / "001-greet" / "hidden_tests" / "test_greet.py"


def test_sealed_and_untouched_tests_are_reported_intact(repo):
    start_battle(repo, ["good"])
    seal_battle(repo, "001-greet")
    gladiator_commits(repo, "good", {"extras/greet.py": GOOD_GREET})

    scorecard = score_battle(repo, "001-greet")

    assert scorecard["seal"] == "intact"
    assert "🔒" in format_scorecard(scorecard)


def test_a_judge_editing_tests_after_the_seal_is_caught(repo):
    start_battle(repo, ["good"])
    seal_battle(repo, "001-greet")
    gladiator_commits(repo, "good", {"extras/greet.py": GOOD_GREET})
    # The judge sees the solution, then quietly makes the tests easier:
    hidden_test_file(repo).write_text("def test_free_points():\n    assert True\n")

    scorecard = score_battle(repo, "001-greet")

    assert scorecard["seal"] == "broken"
    assert "🚨" in format_scorecard(scorecard)
    with pytest.raises(ValueError, match="changed after sealing"):
        merge_winner(repo, "001-greet")


def test_seals_cannot_be_redone(repo):
    start_battle(repo, ["good"])
    seal_battle(repo, "001-greet")

    with pytest.raises(ValueError, match="already sealed"):
        seal_battle(repo, "001-greet")


def test_running_the_tests_does_not_break_the_seal(repo):
    # Running pytest creates __pycache__ inside hidden_tests; that must not count as tampering.
    start_battle(repo, ["good"])
    seal_battle(repo, "001-greet")
    gladiator_commits(repo, "good", {"extras/greet.py": GOOD_GREET})

    score_battle(repo, "001-greet")
    assert score_battle(repo, "001-greet")["seal"] == "intact"


def test_unsealed_battles_are_flagged(repo):
    start_battle(repo, ["good"])
    gladiator_commits(repo, "good", {"extras/greet.py": GOOD_GREET})

    scorecard = score_battle(repo, "001-greet")

    assert scorecard["seal"] == "unsealed"
    assert "never sealed" in format_scorecard(scorecard)
