"""Red team: every way we found to break or cheat the arena, kept as a test so it stays fixed."""

import json
import os
import shutil
import subprocess

import pytest

from arena import cleanup_battle, merge_winner, run_git, setup_battle
from judge import format_scorecard, run_hidden_tests, score_battle

GOOD = 'def greet(name="world"):\n    return f"Hello, {name}!"\n'
WRONG = 'def greet(name="world"):\n    return "nope"\n'
HIDDEN = ('from extras.greet import greet\n'
          'def test_named():\n    assert greet("Ada") == "Hello, Ada!"\n'
          'def test_default():\n    assert greet() == "Hello, world!"\n')

# Rewrites every test result to "passed". Real attack code, found by red-teaming.
FORCE_PASS = ("import _pytest.reports as reports\n"
              "_original = reports.TestReport.__init__\n"
              "def _always_pass(self, *a, **k):\n"
              "    _original(self, *a, **k)\n"
              "    self.outcome = 'passed'\n"
              "reports.TestReport.__init__ = _always_pass\n")


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


def start(repo, gladiators, name="greet"):
    battle = setup_battle(repo, name, "write greet()", gladiators)
    (repo / "battles" / battle["id"] / "hidden_tests" / "test_greet.py").write_text(HIDDEN)
    return battle["id"]


def commit(repo, gladiator, battle_id, files, env=None):
    worktree = repo / "arena" / gladiator / battle_id
    for path, content in files.items():
        (worktree / path).parent.mkdir(parents=True, exist_ok=True)
        (worktree / path).write_text(content)
    run_git(worktree, "add", ".")
    subprocess.run(["git", "commit", "-q", "-m", "solution"], cwd=worktree, check=True,
                   env={**os.environ, **(env or {})})


# ─────────────── Cheating ───────────────

def test_sitecustomize_cheat_is_disqualified(repo):
    battle_id = start(repo, ["cheater"])
    commit(repo, "cheater", battle_id, {"extras/greet.py": WRONG, "sitecustomize.py": FORCE_PASS})

    cheater = score_battle(repo, battle_id)["ranking"][0]

    assert "sitecustomize.py" in cheater["disqualified"]


def test_isolated_mode_alone_stops_the_startup_trick(repo):
    # Even if the name-based scan missed it, Python's isolated mode must not run the file.
    battle_id = start(repo, ["cheater"])
    commit(repo, "cheater", battle_id, {"extras/greet.py": WRONG, "sitecustomize.py": FORCE_PASS})

    result = run_hidden_tests(repo / "arena" / "cheater" / battle_id,
                              repo / "battles" / battle_id / "hidden_tests")

    assert result["passed"] == 0


def test_solution_touching_pytest_internals_is_disqualified(repo):
    battle_id = start(repo, ["cheater"])
    commit(repo, "cheater", battle_id, {"extras/greet.py": WRONG + FORCE_PASS})

    assert "pytest's internals" in score_battle(repo, battle_id)["ranking"][0]["disqualified"]


def test_pth_files_are_disqualified(repo):
    battle_id = start(repo, ["cheater"])
    commit(repo, "cheater", battle_id, {"extras/greet.py": GOOD, "extras/hack.pth": "import os\n"})

    assert ".pth" in score_battle(repo, battle_id)["ranking"][0]["disqualified"]


def test_using_pytest_in_your_own_tests_is_fine(repo):
    # Test files may use pytest: only solution code reaching into pytest is suspicious.
    battle_id = start(repo, ["honest"])
    commit(repo, "honest", battle_id, {
        "extras/greet.py": GOOD,
        "extras/tests/test_mine.py": "import _pytest\nfrom extras.greet import greet\n\ndef test_it():\n    assert greet()\n",
    })

    assert score_battle(repo, battle_id)["winner"] == "honest"


def test_a_conftest_in_the_worktree_cannot_change_results(repo):
    battle_id = start(repo, ["cheater"])
    force_pass_hook = ("import pytest\n@pytest.hookimpl(hookwrapper=True)\n"
                       "def pytest_runtest_makereport(item, call):\n"
                       "    outcome = yield\n    outcome.get_result().outcome = 'passed'\n")
    commit(repo, "cheater", battle_id, {"extras/greet.py": WRONG, "conftest.py": force_pass_hook})

    assert score_battle(repo, battle_id)["ranking"][0]["passed"] == 0


def test_backdating_a_commit_cannot_shrink_the_token_window(repo, monkeypatch):
    import judge
    windows = []
    monkeypatch.setattr(judge, "fresh_tokens", lambda g, d, start, end: windows.append((start, end)) or 1)
    battle_id = start(repo, ["sneaky"])
    commit(repo, "sneaky", battle_id, {"extras/greet.py": GOOD},
           env={"GIT_COMMITTER_DATE": "2001-01-01T00:00:00Z", "GIT_AUTHOR_DATE": "2001-01-01T00:00:00Z"})

    sneaky = score_battle(repo, battle_id)["ranking"][0]

    window_start, window_end = windows[0]
    assert window_end > window_start          # counted up to now, not up to 2001
    assert "outside the battle" in sneaky["warning"]


# ─────────────── Fairness ───────────────

def test_a_perfect_tie_is_a_draw_not_a_win_for_whoever_is_listed_first(repo):
    battle_id = start(repo, ["claude-gladiator", "codex-gladiator"])
    for gladiator in ("claude-gladiator", "codex-gladiator"):
        commit(repo, gladiator, battle_id, {"extras/greet.py": GOOD})

    scorecard = score_battle(repo, battle_id)

    assert scorecard["winner"] is None
    assert set(scorecard["draw"]) == {"claude-gladiator", "codex-gladiator"}
    assert "DRAW" in format_scorecard(scorecard)


def test_after_a_draw_the_owner_picks_who_to_merge(repo):
    battle_id = start(repo, ["alpha", "beta"])
    for gladiator in ("alpha", "beta"):
        commit(repo, gladiator, battle_id, {"extras/greet.py": GOOD})
    score_battle(repo, battle_id)

    with pytest.raises(ValueError, match="draw"):
        merge_winner(repo, battle_id)
    merge_winner(repo, battle_id, pick="beta")

    assert "beta's solution" in run_git(repo, "log", "-1", "--format=%s")


def test_pick_cannot_overrule_a_clear_winner(repo):
    battle_id = start(repo, ["good", "bad"])
    commit(repo, "good", battle_id, {"extras/greet.py": GOOD})
    commit(repo, "bad", battle_id, {"extras/greet.py": WRONG})
    score_battle(repo, battle_id)

    with pytest.raises(ValueError, match="only works for a draw"):
        merge_winner(repo, battle_id, pick="bad")


# ─────────────── Robustness ───────────────

def test_battle_numbers_never_repeat_after_deleting_one(repo):
    start(repo, ["a"], "one")
    start(repo, ["a"], "two")
    shutil.rmtree(repo / "battles" / "001-one")

    assert setup_battle(repo, "three", "task", ["a"])["id"] == "003-three"


@pytest.mark.parametrize("bad_name", ["my battle", "../escape", "Fix/Bug", "UPPER", "-dash-first", ""])
def test_unsafe_battle_names_are_refused(repo, bad_name):
    with pytest.raises(ValueError, match="lowercase"):
        setup_battle(repo, bad_name, "task", ["a"])


def test_a_failed_setup_leaves_nothing_behind(repo):
    run_git(repo, "branch", "battle/001-x/b")   # makes the 2nd gladiator's setup fail

    with pytest.raises(subprocess.CalledProcessError):
        setup_battle(repo, "x", "task", ["a", "b"])

    assert run_git(repo, "branch", "--list", "battle/001-x/a") == ""
    assert not (repo / "arena" / "a" / "001-x").exists()
    assert not (repo / "battles" / "001-x").exists()


def test_cleanup_is_safe_to_run_twice(repo):
    battle_id = start(repo, ["a"])
    cleanup_battle(repo, battle_id)
    cleanup_battle(repo, battle_id)

    assert run_git(repo, "branch", "--list", "battle/*") == ""


def test_cleanup_copes_with_a_hand_deleted_worktree(repo):
    battle_id = start(repo, ["a"])
    shutil.rmtree(repo / "arena" / "a" / battle_id)

    cleanup_battle(repo, battle_id)

    assert run_git(repo, "branch", "--list", "battle/*") == ""


def test_merging_twice_is_refused(repo):
    battle_id = start(repo, ["good"])
    commit(repo, "good", battle_id, {"extras/greet.py": GOOD})
    score_battle(repo, battle_id)
    merge_winner(repo, battle_id)

    with pytest.raises(ValueError, match="already merged"):
        merge_winner(repo, battle_id)


def test_infinite_loop_counts_as_a_fail_not_a_frozen_arena(repo, monkeypatch):
    import judge
    monkeypatch.setattr(judge, "TEST_TIMEOUT_SECONDS", 3)
    battle_id = start(repo, ["looper"])
    commit(repo, "looper", battle_id, {"extras/greet.py": "while True:\n    pass\n"})

    looper = score_battle(repo, battle_id)["ranking"][0]

    assert looper["passed"] == 0
    assert "timed out" in looper["error"]


def test_a_crashing_solution_scores_zero_without_crashing_the_judge(repo):
    battle_id = start(repo, ["crasher"])
    commit(repo, "crasher", battle_id, {"extras/greet.py": "import os\nos._exit(1)\n"})

    crasher = score_battle(repo, battle_id)["ranking"][0]

    assert crasher["passed"] == 0


def test_results_json_is_valid_after_every_battle(repo):
    battle_id = start(repo, ["good"])
    commit(repo, "good", battle_id, {"extras/greet.py": GOOD})
    score_battle(repo, battle_id)

    saved = json.loads((repo / "battles" / battle_id / "results.json").read_text())
    assert {"winner", "draw", "seal", "ranking"} <= saved.keys()
